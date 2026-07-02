"""
hermione_research.py
情報リサーチ担当: YouTube最新動画 + AIニュースRSSの情報収集スクリプト
ステップ①②: リサーチ → 分析 → ブリーフィング生成
"""


# ========== AFFI 認証チェック（編集禁止・自動挿入） ==========
import sys as _affi_sys
from pathlib import Path as _affi_Path
_affi_sys.path.insert(0, str(_affi_Path(__file__).resolve().parent))
try:
    from utils.auth_check import check_auth as _affi_check_auth
    _affi_ok, _affi_msg = _affi_check_auth()
    if not _affi_ok:
        print(f"⛔ {_affi_msg}")
        _affi_sys.exit(1)
except ImportError:
    print("⛔ auth_check モジュールが見つかりません。配布物が破損している可能性があります。")
    _affi_sys.exit(1)
# ========== END 認証チェック ==========
import os
import sys
import json
import argparse
import requests
import feedparser
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from utils.github_issues import GitHubIssues, PIPELINE_STEPS
from utils.gemini_client import call_gemini
from dotenv import load_dotenv
from loguru import logger

load_dotenv()

SPREADSHEET_ID          = os.getenv("SPREADSHEET_ID", "")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials/sheets_service_account.json")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
RECYCLING_TRACKER_PATH  = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "recycling_tracker.json")

# ── 設定 ──────────────────────────────────────────
YOUTUBE_API_KEY     = os.getenv("YOUTUBE_API_KEY")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY")
GITHUB_TOKEN        = os.getenv("GITHUB_TOKEN")
GITHUB_REPO         = os.getenv("GITHUB_REPO")   # "owner/repo"
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

# ★ ジャンル設定は operation/config/genre_config.yaml から読み込む
def _load_genre_config_safe() -> dict:
    """ジャンル設定を読み込む（情報リサーチは設定なしでも続行可能・警告のみ）"""
    cfg_path = os.path.join(SCRIPT_DIR, "..", "operation", "config", "genre_config.yaml")
    if not os.path.exists(cfg_path):
        logger.warning(f"ジャンル設定が見つかりません: {cfg_path}（情報リサーチはスキップ多め）")
        return {}
    try:
        import yaml
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        # プレースホルダ残存ならハードストップ
        raw = open(cfg_path, "r", encoding="utf-8").read()
        if "{{" in raw and "}}" in raw:
            logger.error("operation/config/genre_config.yaml にプレースホルダが残っています。「始める」で記入してください。")
            sys.exit(1)
        return cfg
    except Exception as e:
        logger.warning(f"ジャンル設定の読み込み失敗: {e}")
        return {}


_GENRE_CFG = _load_genre_config_safe()
YOUTUBE_CHANNEL_IDS    = [c for c in (_GENRE_CFG.get("youtube_channel_ids") or []) if c and "{{" not in c]
YOUTUBE_KEYWORD_SEARCHES = [c for c in (_GENRE_CFG.get("youtube_keyword_searches") or []) if c and "{{" not in c]
GOOGLE_TRENDS_KEYWORDS = [c for c in (_GENRE_CFG.get("google_trends_keywords") or []) if c and "{{" not in c]
RSS_FEEDS              = [c for c in (_GENRE_CFG.get("rss_feeds") or []) if c]

BUZZ_POSTS_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "buzz_posts.md")
WEEKLY_DIR      = os.path.join(SCRIPT_DIR, "..", "operation", "weekly")

def get_latest_youtube_videos(max_results: int = 5) -> list[dict]:
    """登録チャンネルの最新動画を取得する"""
    if not YOUTUBE_API_KEY or not YOUTUBE_CHANNEL_IDS:
        logger.warning("YouTube API Key or Channel IDs not set. Skipping YouTube fetch.")
        return []

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    videos = []
    since = datetime.now(timezone.utc) - timedelta(days=3)

    for channel_id in YOUTUBE_CHANNEL_IDS:
        try:
            resp = youtube.search().list(
                part="snippet",
                channelId=channel_id,
                maxResults=max_results,
                order="date",
                publishedAfter=since.isoformat(),
                type="video"
            ).execute()

            for item in resp.get("items", []):
                videos.append({
                    "title": item["snippet"]["title"],
                    "description": item["snippet"]["description"][:300],
                    "published_at": item["snippet"]["publishedAt"],
                    "video_id": item["id"]["videoId"],
                    "channel": item["snippet"]["channelTitle"],
                })
        except Exception as e:
            logger.error(f"YouTube API error for channel {channel_id}: {e}")

    logger.info(f"YouTube: {len(videos)} videos fetched")
    return videos


def search_youtube_by_keywords(max_results: int = 3) -> list[dict]:
    """キーワードでYouTube最新動画を検索する（AIエージェント・Claude Code等）"""
    if not YOUTUBE_API_KEY or not YOUTUBE_KEYWORD_SEARCHES:
        return []

    youtube = build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    videos = []
    since = datetime.now(timezone.utc) - timedelta(days=7)

    for keyword in YOUTUBE_KEYWORD_SEARCHES:
        try:
            resp = youtube.search().list(
                part="snippet",
                q=keyword,
                maxResults=max_results,
                order="date",
                publishedAfter=since.isoformat(),
                type="video",
                regionCode="JP",
                relevanceLanguage="ja",
            ).execute()

            for item in resp.get("items", []):
                videos.append({
                    "title": item["snippet"]["title"],
                    "description": item["snippet"]["description"][:200],
                    "published_at": item["snippet"]["publishedAt"],
                    "video_id": item["id"]["videoId"],
                    "channel": item["snippet"]["channelTitle"],
                    "keyword": keyword,
                })
        except Exception as e:
            logger.error(f"YouTube keyword search error [{keyword}]: {e}")

    logger.info(f"YouTube keyword search: {len(videos)} videos found")
    return videos


def get_google_trends_data() -> list[dict]:
    """Google Trendsでジャンル設定キーワードの鮮度を取得する。週次で使う想定"""
    if not GOOGLE_TRENDS_KEYWORDS:
        return []
    try:
        from pytrends.request import TrendReq
    except ImportError:
        logger.warning("pytrends not installed. Skipping Google Trends.")
        return []

    results = []
    try:
        pytrends = TrendReq(hl='ja-JP', tz=540)  # JST = UTC+9 → 540分
        # 5キーワードずつ処理（pytrendsの仕様）
        chunks = [GOOGLE_TRENDS_KEYWORDS[i:i+5] for i in range(0, len(GOOGLE_TRENDS_KEYWORDS), 5)]
        for chunk in chunks:
            pytrends.build_payload(chunk, timeframe='now 7-d', geo='JP')
            data = pytrends.interest_over_time()
            if data.empty:
                continue
            for kw in chunk:
                if kw in data.columns:
                    recent = data[kw].tail(3).mean()  # 直近3時点の平均
                    prev = data[kw].head(3).mean()    # 開始3時点の平均
                    trend = "上昇" if recent > prev * 1.1 else ("下降" if recent < prev * 0.9 else "横ばい")
                    results.append({
                        "keyword": kw,
                        "recent_score": round(float(recent), 1),
                        "trend": trend,
                    })
    except Exception as e:
        logger.error(f"Google Trends error: {e}")

    logger.info(f"Google Trends: {len(results)} keywords analyzed")
    return results


def get_latest_rss_news(max_per_feed: int = 3) -> list[dict]:
    """RSSフィードから最新ニュースを取得する"""
    news_items = []
    since = datetime.now() - timedelta(hours=48)

    for feed_url in RSS_FEEDS:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:max_per_feed]:
                news_items.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", "")[:300],
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", feed_url),
                })
        except Exception as e:
            logger.error(f"RSS parse error for {feed_url}: {e}")

    logger.info(f"RSS: {len(news_items)} articles fetched")
    return news_items


def load_performance_summary() -> dict:
    """
    Google Sheetsから直近7日間の実績データを取得して要約する。
    閲覧数・エンゲージメント率・スロット別分析・個別投稿パフォーマンスを含む。
    Sheetsが未設定またはデータがない場合は空dictを返す。
    """
    summary = {
        "follower_3d_diff": None,           # 3日間のフォロワー変化数
        "follower_trend": "不明",            # "増加" / "減少" / "横ばい"
        "avg_likes_7d": None,                # 7日平均いいね
        "avg_views_7d": None,                # 7日平均閲覧数
        "avg_engagement_rate_7d": None,      # 7日平均エンゲージメント率(%)
        "best_pattern": "",                  # 最高パフォーマンス投稿の特徴
        "worst_pattern": "",                 # 最低パフォーマンス投稿の特徴
        "hook_analysis": "",                 # フック別パフォーマンス分析
        "format_analysis": "",               # フォーマット別パフォーマンス分析
        "winning_pattern": {},               # 勝ちパターン（hook + format + ER）
        "experiment_suggestion": {},         # 実験枠の提案
        "slot_analysis": "",                 # スロット別パフォーマンス分析
        "individual_posts": [],              # 個別投稿のパフォーマンスリスト
    }
    if not SPREADSHEET_ID or not GOOGLE_CREDENTIALS_PATH:
        return summary
    try:
        from utils.sheets_logger import _get_client, _PROJECT_ROOT, HEADERS
        creds_path = GOOGLE_CREDENTIALS_PATH
        if not os.path.isabs(creds_path):
            creds_path = os.path.join(_PROJECT_ROOT, creds_path)
        if not os.path.exists(creds_path):
            return summary

        client = _get_client(creds_path)
        spreadsheet = client.open_by_key(SPREADSHEET_ID)

        # フォロワー推移から3日間トレンドを取得
        try:
            import gspread
            fw_sheet = spreadsheet.worksheet("フォロワー推移")
            fw_rows = fw_sheet.get_all_values()
            if len(fw_rows) >= 4:
                data_rows = fw_rows[1:]
                try:
                    latest  = int(data_rows[-1][3])
                    three_d = int(data_rows[-3][3]) if len(data_rows) >= 3 else latest
                    diff = latest - three_d
                    summary["follower_3d_diff"] = diff
                    summary["follower_trend"] = "増加" if diff > 0 else ("減少" if diff < 0 else "横ばい")
                except (ValueError, IndexError):
                    pass
        except Exception:
            pass

        # ── 投稿ログから7日間の詳細分析 ──
        try:
            log_sheet = spreadsheet.worksheet("投稿ログ")
            log_rows = log_sheet.get_all_values()
            if len(log_rows) >= 3:
                header = log_rows[0]
                data_rows = log_rows[1:][-21:]  # 直近21行（7日×3スロット）

                # カラムインデックスを動的に検出（ヘッダーが変わっても対応）
                def col_idx(name, fallback=-1):
                    return header.index(name) if name in header else fallback

                idx_date  = col_idx("日付", 0)
                idx_slot  = col_idx("スロット", 2)
                idx_text  = col_idx("1投稿目テキスト", 4)
                idx_likes = col_idx("いいね数", 7)
                idx_views = col_idx("閲覧数", 10)

                # 個別投稿データを収集（フック・フォーマット分類付き）
                from utils.post_classifier import classify_hook_type, classify_format_type

                posts_data = []
                for row in data_rows:
                    try:
                        likes = int(row[idx_likes]) if len(row) > idx_likes and row[idx_likes] else 0
                        views = int(row[idx_views]) if idx_views >= 0 and len(row) > idx_views and row[idx_views] else 0
                        date_str = row[idx_date] if len(row) > idx_date else ""
                        slot_str = row[idx_slot] if len(row) > idx_slot else ""
                        full_text = row[idx_text] if len(row) > idx_text else ""
                        text_preview = full_text[:50]
                        er = round(likes / views * 100, 2) if views > 0 else 0

                        posts_data.append({
                            "date": date_str,
                            "slot": slot_str,
                            "likes": likes,
                            "views": views,
                            "engagement_rate": er,
                            "text_preview": text_preview,
                            "hook_type": classify_hook_type(full_text[:150]),
                            "format_type": classify_format_type(full_text[:200]),
                        })
                    except (ValueError, IndexError):
                        pass

                # 計測済み（likes or viewsが1以上）のデータのみでサマリー計算
                measured = [p for p in posts_data if p["likes"] > 0 or p["views"] > 0]
                summary["individual_posts"] = measured

                if measured:
                    avg_likes = sum(p["likes"] for p in measured) / len(measured)
                    avg_views = sum(p["views"] for p in measured) / len(measured)
                    total_likes = sum(p["likes"] for p in measured)
                    total_views = sum(p["views"] for p in measured)
                    avg_er = round(total_likes / total_views * 100, 2) if total_views > 0 else 0

                    summary["avg_likes_7d"] = round(avg_likes, 1)
                    summary["avg_views_7d"] = round(avg_views, 1)
                    summary["avg_engagement_rate_7d"] = avg_er

                    # ベスト/ワースト（ER基準）
                    sorted_by_er = sorted(measured, key=lambda x: x["engagement_rate"], reverse=True)
                    best = sorted_by_er[0]
                    worst = sorted_by_er[-1]
                    summary["best_pattern"] = (
                        f"{best['date']} {best['slot']}: ER {best['engagement_rate']}% "
                        f"(いいね{best['likes']}/閲覧{best['views']}) "
                        f"「{best['text_preview']}...」"
                    )
                    summary["worst_pattern"] = (
                        f"{worst['date']} {worst['slot']}: ER {worst['engagement_rate']}% "
                        f"(いいね{worst['likes']}/閲覧{worst['views']}) "
                        f"「{worst['text_preview']}...」"
                    )

                    # ── スロット別パフォーマンス分析 ──
                    slot_stats = {}
                    for p in measured:
                        slot_key = p["slot"]
                        if slot_key not in slot_stats:
                            slot_stats[slot_key] = {"likes": [], "views": []}
                        slot_stats[slot_key]["likes"].append(p["likes"])
                        slot_stats[slot_key]["views"].append(p["views"])

                    slot_lines = []
                    best_slot = None
                    best_slot_er = -1
                    for slot_key in sorted(slot_stats.keys()):
                        s = slot_stats[slot_key]
                        s_likes = sum(s["likes"]) / len(s["likes"]) if s["likes"] else 0
                        s_views = sum(s["views"]) / len(s["views"]) if s["views"] else 0
                        s_er = round(sum(s["likes"]) / sum(s["views"]) * 100, 2) if sum(s["views"]) > 0 else 0
                        slot_lines.append(
                            f"- {slot_key}: 平均いいね{round(s_likes,1)} / 平均閲覧{round(s_views,0)} / ER {s_er}%"
                        )
                        if s_er > best_slot_er:
                            best_slot_er = s_er
                            best_slot = slot_key

                    if best_slot:
                        slot_lines.append(f"→ 最高パフォーマンスは{best_slot}。この時間帯の角度を強化すべき。")
                    summary["slot_analysis"] = "\n".join(slot_lines)

                    # ── フック別パフォーマンス分析 ──
                    from collections import defaultdict
                    hook_stats = defaultdict(lambda: {"ers": [], "count": 0})
                    format_stats = defaultdict(lambda: {"ers": [], "count": 0})
                    combo_stats = defaultdict(lambda: {"ers": [], "count": 0})

                    for p in measured:
                        h = p.get("hook_type", "不明")
                        f = p.get("format_type", "不明")
                        er_val = p["engagement_rate"]
                        hook_stats[h]["ers"].append(er_val)
                        hook_stats[h]["count"] += 1
                        format_stats[f]["ers"].append(er_val)
                        format_stats[f]["count"] += 1
                        combo_stats[f"{h}×{f}"]["ers"].append(er_val)
                        combo_stats[f"{h}×{f}"]["count"] += 1

                    # フック別分析テキスト
                    hook_lines = []
                    all_hooks = ["好奇心", "共感", "驚き", "危機感"]
                    best_hook_er = -1
                    best_hook_name = ""
                    for h in all_hooks:
                        s = hook_stats.get(h)
                        if s and s["count"] > 0:
                            avg = round(sum(s["ers"]) / len(s["ers"]), 2)
                            star = ""
                            if avg > best_hook_er:
                                best_hook_er = avg
                                best_hook_name = h
                            hook_lines.append(f"- {h}: 平均ER {avg}%（{s['count']}件）")
                        else:
                            hook_lines.append(f"- {h}: データなし（未テスト）")
                    # ★マーク付与
                    hook_lines = [l + " ★最高" if best_hook_name and best_hook_name in l and "★" not in l else l for l in hook_lines]
                    summary["hook_analysis"] = "\n".join(hook_lines)

                    # フォーマット別分析テキスト
                    fmt_lines = []
                    all_fmts = ["リスト", "体験談", "対比", "質問"]
                    best_fmt_er = -1
                    best_fmt_name = ""
                    for f in all_fmts:
                        s = format_stats.get(f)
                        if s and s["count"] > 0:
                            avg = round(sum(s["ers"]) / len(s["ers"]), 2)
                            if avg > best_fmt_er:
                                best_fmt_er = avg
                                best_fmt_name = f
                            fmt_lines.append(f"- {f}: 平均ER {avg}%（{s['count']}件）")
                        else:
                            fmt_lines.append(f"- {f}: データなし（未テスト）")
                    fmt_lines = [l + " ★最高" if best_fmt_name and best_fmt_name in l and "★" not in l else l for l in fmt_lines]
                    summary["format_analysis"] = "\n".join(fmt_lines)

                    # ── 勝ちパターンの特定 ──
                    if best_hook_name and best_fmt_name:
                        combo_key = f"{best_hook_name}×{best_fmt_name}"
                        c = combo_stats.get(combo_key, {"ers": [], "count": 0})
                        combo_er = round(sum(c["ers"]) / len(c["ers"]), 2) if c["ers"] else best_hook_er
                        summary["winning_pattern"] = {
                            "hook": best_hook_name,
                            "format": best_fmt_name,
                            "avg_er": combo_er,
                            "sample_count": c["count"] if c["count"] > 0 else 1,
                        }

                    # ── 実験枠の提案 ──
                    # 未テスト or 最少データの組み合わせを選ぶ
                    experiment_hooks = [h for h in all_hooks if h != best_hook_name]
                    experiment_fmts = [f for f in all_fmts if f != best_fmt_name]

                    # 未テストを優先
                    untested_hooks = [h for h in experiment_hooks if hook_stats.get(h, {}).get("count", 0) == 0]
                    untested_fmts = [f for f in experiment_fmts if format_stats.get(f, {}).get("count", 0) == 0]

                    exp_hook = untested_hooks[0] if untested_hooks else (experiment_hooks[0] if experiment_hooks else "好奇心")
                    exp_fmt = untested_fmts[0] if untested_fmts else (experiment_fmts[0] if experiment_fmts else "リスト")
                    exp_reason = "未テストの組み合わせ" if (untested_hooks or untested_fmts) else "データ不足（低サンプル）"

                    summary["experiment_suggestion"] = {
                        "hook": exp_hook,
                        "format": exp_fmt,
                        "reason": exp_reason,
                    }

        except Exception as e:
            logger.warning(f"投稿ログ分析スキップ: {e}")

    except Exception as e:
        logger.warning(f"実績データ取得スキップ: {e}")
    return summary


def check_recycle_mode() -> dict | None:
    """
    ヒットリサイクルモードに入るか判定する。
    recycling_tracker.jsonを確認し、前回リサイクルから3日以上経過していれば
    リサイクル候補の投稿情報を返す。そうでなければNoneを返す。
    """
    today = datetime.now().strftime("%Y-%m-%d")

    # トラッカーを読み込む（なければ初期化）
    tracker = {"interval_days": 3, "last_recycle_date": None, "history": []}
    try:
        with open(RECYCLING_TRACKER_PATH, "r", encoding="utf-8") as f:
            tracker = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # 前回リサイクルから interval_days 日以上経過しているか確認
    last_date = tracker.get("last_recycle_date")
    if last_date:
        days_since = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(last_date, "%Y-%m-%d")).days
        if days_since < tracker.get("interval_days", 3):
            logger.info(f"リサイクルまであと{tracker['interval_days'] - days_since}日")
            return None

    # buzz_posts.mdから最高いいねのリサイクル候補を選ぶ
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return None

    # 最近リサイクルした投稿番号を除外リストに
    recent_recycled = [h.get("post_no") for h in tracker.get("history", [])[-3:]]

    # バズ投稿テーブルを解析（| No. | 日付 | いいね | テーマ | ... |）
    best_candidate = None
    best_likes = 0
    for line in content.split("\n"):
        if not line.startswith("|") or "---" in line or "No." in line:
            continue
        cols = [c.strip() for c in line.strip("|").split("|")]
        if len(cols) < 6:
            continue
        try:
            post_no = cols[0].strip()
            likes   = int(cols[2].strip())
            theme   = cols[3].strip()
            excerpt = cols[5].strip()
            if post_no not in recent_recycled and likes > best_likes:
                best_likes = likes
                best_candidate = {"post_no": post_no, "likes": likes, "theme": theme, "excerpt": excerpt}
        except (ValueError, IndexError):
            continue

    if not best_candidate:
        logger.info("リサイクル候補なし（buzz_posts.mdにデータがない）")
        return None

    logger.info(f"🔄 リサイクルモード発動: No.{best_candidate['post_no']} (いいね{best_candidate['likes']})")
    return best_candidate


def update_recycle_tracker(post_no: str, theme: str):
    """リサイクル実施後にトラッカーを更新する"""
    tracker = {"interval_days": 3, "last_recycle_date": None, "history": []}
    try:
        with open(RECYCLING_TRACKER_PATH, "r", encoding="utf-8") as f:
            tracker = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    today = datetime.now().strftime("%Y-%m-%d")
    tracker["last_recycle_date"] = today
    tracker["history"].append({"date": today, "post_no": post_no, "theme": theme})
    tracker["history"] = tracker["history"][-30:]  # 直近30件まで保持

    os.makedirs(os.path.dirname(RECYCLING_TRACKER_PATH), exist_ok=True)
    with open(RECYCLING_TRACKER_PATH, "w", encoding="utf-8") as f:
        json.dump(tracker, f, ensure_ascii=False, indent=2)
    logger.info(f"リサイクルトラッカー更新: {today}")


def load_snape_insights() -> str:
    """
    監視の最新週次レポートから改善提案・注意事項を読み込み、
    情報リサーチのブリーフィングに自動反映するためのテキストを返す。
    レポートがなければ空文字を返す。
    """
    import glob as glob_mod
    pattern = os.path.join(WEEKLY_DIR, "snape_report_*.md")
    reports = sorted(glob_mod.glob(pattern))
    if not reports:
        logger.info("監視週次レポートなし（初回 or 未生成）")
        return ""

    latest_report = reports[-1]
    logger.info(f"監視レポート読み込み: {os.path.basename(latest_report)}")

    try:
        with open(latest_report, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return ""

    # ④ 改善提案 と ⑤ 来週の注意事項 のセクションを抽出
    sections = []
    import re as re_mod
    for header in [r"## ④ 改善提案", r"## ⑤ 来週の注意事項", r"## ② エンゲージメント推移"]:
        match = re_mod.search(rf"({header}.*?)(?=\n## |\Z)", content, re_mod.DOTALL)
        if match:
            sections.append(match.group(1).strip())

    if not sections:
        return ""

    return "\n\n".join(sections)


def load_buzz_posts() -> str:
    """buzz_posts.md を読み込む"""
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"{BUZZ_POSTS_PATH} not found. Proceeding without buzz history.")
        return "（バズ投稿データなし）"


def generate_briefing(videos: list, news: list, buzz_posts: str, theme: str,
                      performance: dict = None, recycle_candidate: dict = None,
                      snape_insights: str = "", trends: list = None) -> str:
    """Gemini Flash でブリーフィングを生成する（タイムアウト・フォールバック付き）"""

    # Google Trendsデータのセクション
    trends_section = ""
    if trends:
        rising = [t for t in trends if t.get("trend") == "上昇"]
        trends_lines = [f"- 【{t['keyword']}】検索熱: {t['recent_score']} / 傾向: {t['trend']}" for t in trends]
        trends_section = "\n## 🔥 Google Trends（ジャンルキーワードの鮮度）\n" + "\n".join(trends_lines)
        if rising:
            trends_section += f"\n\n**特に上昇中**: {', '.join([t['keyword'] for t in rising])} → この話題を投稿に織り込む優先度が高い"

    # パフォーマンスデータセクションを組み立て
    perf_section = ""
    if performance and any(v is not None for v in performance.values()):
        trend = performance.get("follower_trend", "不明")
        diff  = performance.get("follower_3d_diff")
        avg   = performance.get("avg_likes_7d")
        best  = performance.get("best_pattern", "")
        worst = performance.get("worst_pattern", "")

        diff_str = f"+{diff}人" if diff and diff > 0 else (f"{diff}人" if diff is not None else "計測中")
        avg_str  = f"{avg}件" if avg is not None else "計測中"

        avg_views = performance.get("avg_views_7d")
        avg_er    = performance.get("avg_engagement_rate_7d")
        slot_analysis    = performance.get("slot_analysis", "")
        individual_posts = performance.get("individual_posts", [])

        avg_views_str = f"{avg_views}件" if avg_views is not None else "計測中"
        avg_er_str    = f"{avg_er}%" if avg_er is not None else "計測中"

        perf_section = f"""
## 📊 直近の実績データ（最優先で分析に反映すること）
フォロワー推移（直近3日）: {diff_str} → **{trend}傾向**
直近7日の平均いいね: {avg_str}
直近7日の平均閲覧数: {avg_views_str}
平均エンゲージメント率（いいね/閲覧）: {avg_er_str}
{f"✅ 高パフォーマンス投稿: {best}" if best else ""}
{f"❌ 低パフォーマンス投稿: {worst}" if worst else ""}
"""

        if slot_analysis:
            perf_section += f"""
### スロット別パフォーマンス
{slot_analysis}
"""

        if individual_posts:
            perf_section += "\n### 直近の個別投稿パフォーマンス（ライターへの具体的ヒント）\n"
            for p in individual_posts[-9:]:  # 直近9件（3日分）
                er_str = f"{p['engagement_rate']}%" if p.get('engagement_rate') else "-"
                perf_section += (
                    f"- {p['date']} {p['slot']}: "
                    f"いいね{p['likes']} / 閲覧{p['views']} / ER {er_str} / "
                    f"「{p['text_preview']}...」\n"
                )

        # ── フック/フォーマット分析をブリーフィングに追加 ──
        hook_analysis = performance.get("hook_analysis", "")
        format_analysis = performance.get("format_analysis", "")
        winning = performance.get("winning_pattern", {})
        experiment = performance.get("experiment_suggestion", {})

        if hook_analysis:
            perf_section += f"\n### 感情フック別パフォーマンス\n{hook_analysis}\n"
        if format_analysis:
            perf_section += f"\n### フォーマット別パフォーマンス\n{format_analysis}\n"

        # ── 安定枠/実験枠の具体的指示 ──
        if winning.get("hook") and experiment.get("hook"):
            perf_section += f"""
→ 【安定枠の指示（SLOT_1 + SLOT_2）】
  勝ちパターン: 感情フック「{winning['hook']}」× フォーマット「{winning['format']}」（平均ER {winning['avg_er']}%, {winning['sample_count']}件実績）
  → SLOT_1とSLOT_2はこの組み合わせをベースに、異なるテーマで2本作成すること。

→ 【実験枠の指示（SLOT_3 = 21時）】
  実験パターン: 感情フック「{experiment['hook']}」× フォーマット「{experiment['format']}」（理由: {experiment['reason']}）
  → SLOT_3は意図的にこの新しい組み合わせを試すこと。成功すれば翌日から安定枠に昇格する。
"""
        else:
            # データ不足時のフォールバック
            perf_section += f"""
→ 【重要】{trend}傾向のパターンを分析し、以下の戦略を取ること：
{"→ 増加しているパターンを継続・強化する。同じ感情フック・形式を別テーマで応用する。" if trend == "増加" else ""}
{"→ 現在のパターンから脱却し、別の感情フック・フォーマット・角度を試す。" if trend == "減少" else ""}
{"→ 変化をつけるタイミング。多様な角度でテストしながら、反応を見る。" if trend in ("横ばい", "不明") else ""}
"""

    # リサイクルセクション
    recycle_section = ""
    if recycle_candidate:
        recycle_section = f"""
## 🔄 本日はヒットリサイクルday（{datetime.now().strftime('%Y-%m-%d')}）
過去のヒット投稿（いいね{recycle_candidate['likes']}件）を、全く新しい形式で書き直すスロットを1つ用意すること。

元の投稿No.: {recycle_candidate['post_no']}
テーマ: {recycle_candidate['theme']}
冒頭: 「{recycle_candidate['excerpt']}」

【ライターへの指示】
- 同じ「核心メッセージ」を保ちながら、以下を全て変える：
  ・フォーマット（体験談→リスト、リスト→対比、等）
  ・導入の形（疑問形→数字、共感→危機感、等）
  ・視点（自分→読者、メリット→デメリット回避、等）
- 同じ言葉・フレーズの繰り返しは厳禁
- このリサイクルスロットはSLOT_2（18時）に使うこと
"""

    prompt = f"""
あなたはThreads運用のリサーチ・分析担当「情報リサーチ」です。
以下のデータをもとに、今日の投稿ライター（ライター）向けブリーフィングを作成してください。

## 今日のテーマ方針
{theme if theme else "（指定なし：自動選定してください）"}

## 収集したYouTube最新動画（ジャンルキーワード検索）
※ keyword フィールドがある動画は「ジャンル設定キーワード」等でヒットした最新情報です
{json.dumps(videos, ensure_ascii=False, indent=2)}

## 収集したニュース・記事
{json.dumps(news, ensure_ascii=False, indent=2)}
{perf_section}
{trends_section}
{recycle_section}
{f'''## 🔦 監視レポートからの改善指示（必ず反映すること）
{snape_insights}
''' if snape_insights else ''}
## 過去のバズ投稿データ（抜粋）
{buzz_posts[:2000]}

---
以下のフォーマットでブリーフィングを出力してください：

【本日のブリーフィング】
推奨ネタ: [ネタの要約（1〜2文）]
角度: [どういう切り口で書くか]
感情フック: [好奇心/共感/驚き/危機感のどれか]
参考バズ投稿: [類似の過去投稿No.（あれば）]
NGワード/注意点: [あれば]
リサーチ元: [YouTube動画タイトル or ニュース記事タイトル]
"""

    return call_gemini(prompt, GEMINI_API_KEY)


def load_affiliate_context() -> str:
    """アフィリチーム用の追加コンテキスト（商品・口コミ・週次計画）を読み込む"""
    import json as _json
    from datetime import datetime as _dt

    script_dir = os.path.dirname(os.path.abspath(__file__))
    today = _dt.now().strftime("%Y-%m-%d")
    context_parts = []

    # 商品リサーチ結果
    products_file = os.path.join(script_dir, "..", "operation", "products", f"{today}.json")
    if os.path.exists(products_file):
        try:
            with open(products_file, "r", encoding="utf-8") as f:
                data = _json.load(f)
            prods = data.get("products", [])[:5]
            if prods:
                context_parts.append("## 🛒 商品リサーチ結果（本日の候補商品）")
                for p in prods:
                    context_parts.append(f"- {p.get('name','')[:60]} / {p.get('price','?')}円 / ★{p.get('review_average','?')}")
        except Exception:
            pass

    # 週次ファネル計画
    week_str = _dt.now().strftime("%YW%V")
    funnel_file = os.path.join(script_dir, "..", "operation", "weekly", f"funnel_{week_str}.md")
    if os.path.exists(funnel_file):
        try:
            with open(funnel_file, "r", encoding="utf-8") as f:
                context_parts.append("## 📅 今週のファネル計画")
                context_parts.append(f.read()[:1500])
        except Exception:
            pass

    return "\n\n".join(context_parts) if context_parts else ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="", help="今日のテーマ（省略可）")
    parser.add_argument("--product-json", default="", help="商品リサーチJSON（アフィリチーム用）")
    args = parser.parse_args()

    logger.info("=== 情報リサーチ リサーチ開始 ===")

    gh = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_or_create_today_issue()
    gh.update_pipeline_status(issue.number, "info_researcher", "running")

    try:
        videos = get_latest_youtube_videos()
        keyword_videos = search_youtube_by_keywords()
        videos = videos + keyword_videos
        news = get_latest_rss_news()
        trends = get_google_trends_data()
        buzz_posts = load_buzz_posts()
        performance = load_performance_summary()
        recycle_candidate = check_recycle_mode()
        snape_insights = load_snape_insights()

        briefing = generate_briefing(videos, news, buzz_posts, args.theme, performance, recycle_candidate, snape_insights, trends)
        logger.info("ブリーフィング生成完了")

        comment_body = f"""## 🔍 情報リサーチより：リサーチ＆分析完了

**実行日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

{briefing}

---
*ライター、上記ブリーフィングをもとに投稿案3案を作成してください。*
"""
        gh.add_comment(issue.number, comment_body)
        done_ts = datetime.now().strftime("%H:%M")
        gh.update_pipeline_status(issue.number, "info_researcher", "done", done_ts)
        logger.info(f"GitHub Issue #{issue.number} にコメントを追加しました")

        if recycle_candidate:
            update_recycle_tracker(recycle_candidate["post_no"], recycle_candidate["theme"])

        logger.info("=== 情報リサーチ リサーチ完了 ===")

    except Exception as e:
        logger.error(f"情報リサーチ実行失敗: {type(e).__name__}: {e}")
        gh.update_pipeline_status(issue.number, "info_researcher", "error")
        gh.add_comment(issue.number, f"## ❌ 情報リサーチ: エラー発生\n\n```\n{type(e).__name__}: {str(e)[:500]}\n```")
        url = os.getenv("DISCORD_WEBHOOK_URL", "")
        if url:
            try:
                requests.post(url, json={"content": f"❌ 情報リサーチ実行エラー: {type(e).__name__}: {str(e)[:200]}"}, timeout=10)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
