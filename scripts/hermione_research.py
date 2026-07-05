"""
hermione_research.py
ハーマイオニー担当: YouTube最新動画 + AIニュースRSSの情報収集スクリプト
ステップ①②: リサーチ → 分析 → ブリーフィング生成
"""

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
from utils.agent_config import name as _n
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

# ── リサーチ設定（operation/config/research_config.json から自動読み込み）──
def _load_research_config() -> dict:
    cfg_path = os.path.join(SCRIPT_DIR, "..", "operation", "config", "research_config.json")
    try:
        with open(cfg_path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

_research_cfg = _load_research_config()

# ★ 監視したいYouTubeチャンネルID（operation/config/research_config.json で変更可能）
YOUTUBE_CHANNEL_IDS = _research_cfg.get("youtube_channel_ids", [
    "UCfapRkagDtoQEkGeyD3uERQ",  # KEITO【AI&WEB ch】
    "UCboaqA4fwGpljEKeUjO1iVQ",  # SHIFT AI ニュース
    "UCopTsucSPUP_N5n4fcLQtXQ",  # ここなのAI大学
    "UCvHpETRVi1tXeRJoYiXHJqw",  # まさおAIじっくり解説ch
    "UCZQVTC3uLCyuJUOcRlguazA",  # にゃんたのAIチャンネル
])

# ★ キーワード検索でトレンド動画を拾う設定（research_config.json で変更可能）
YOUTUBE_KEYWORD_SEARCHES = _research_cfg.get("youtube_keywords", [
    "腸活 やり方",
    "腸内環境 改善 習慣",
    "デトックス 食事",
    "発酵食品 効果",
    "夜勤 疲れ 食事",
])

# ★ 購読するRSSフィード（research_config.json で変更可能）
RSS_FEEDS = _research_cfg.get("rss_feeds", [])

TOPIC_GENRE = _research_cfg.get("topic_genre", "腸活・美容・健康")

BUZZ_POSTS_PATH = os.path.join(SCRIPT_DIR, "..", "operation", "knowledge", "kb_sys_ref_v001.md")
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


def get_latest_rss_news(max_per_feed: int = 3) -> list[dict]:
    """RSSフィードから最新AIニュースを取得する"""
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

                # 個別投稿データを収集
                posts_data = []
                for row in data_rows:
                    try:
                        likes = int(row[idx_likes]) if len(row) > idx_likes and row[idx_likes] else 0
                        views = int(row[idx_views]) if idx_views >= 0 and len(row) > idx_views and row[idx_views] else 0
                        date_str = row[idx_date] if len(row) > idx_date else ""
                        slot_str = row[idx_slot] if len(row) > idx_slot else ""
                        text_preview = row[idx_text][:50] if len(row) > idx_text else ""
                        er = round(likes / views * 100, 2) if views > 0 else 0

                        posts_data.append({
                            "date": date_str,
                            "slot": slot_str,
                            "likes": likes,
                            "views": views,
                            "engagement_rate": er,
                            "text_preview": text_preview,
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

    # kb_sys_ref_v001.mdから最高いいねのリサイクル候補を選ぶ
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
        logger.info("リサイクル候補なし（kb_sys_ref_v001.mdにデータがない）")
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
    スネイプの最新週次レポートから改善提案・注意事項を読み込み、
    ハーマイオニーのブリーフィングに自動反映するためのテキストを返す。
    レポートがなければ空文字を返す。
    """
    import glob as glob_mod
    pattern = os.path.join(WEEKLY_DIR, "snape_report_*.md")
    reports = sorted(glob_mod.glob(pattern))
    if not reports:
        logger.info("スネイプ週次レポートなし（初回 or 未生成）")
        return ""

    latest_report = reports[-1]
    logger.info(f"スネイプレポート読み込み: {os.path.basename(latest_report)}")

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


def load_voice_definition() -> str:
    """kb_sys_ref_v001.mdから声定義セクションを抽出する"""
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        marker = "## 🎤 自分のアカウントの声"
        if marker in content:
            start = content.index(marker)
            end = content.find("\n## ", start + len(marker))
            return content[start:end].strip() if end != -1 else content[start:].strip()
        return ""
    except FileNotFoundError:
        return ""


def is_health_persona(voice_def: str) -> bool:
    """腸活・健康系ペルソナかどうか（AI運用系とブリーフィング形式を切り替える）"""
    if not voice_def:
        return TOPIC_GENRE and not any(k in TOPIC_GENRE for k in ("AI", "Claude", "自動化"))
    health_markers = ("腸活", "腸デトックス", "看護師", "SARI", "添加物", "デトックス")
    ai_markers = ("ChatGPT", "OpenClaw", "Claude Code", "AIツール", "AIエージェント")
    health_score = sum(1 for m in health_markers if m in voice_def)
    ai_score = sum(1 for m in ai_markers if m in voice_def)
    return health_score >= ai_score


def _briefing_slot_block(slot_label: str, health_mode: bool) -> str:
    if health_mode:
        return f"""### {slot_label}
推奨ネタ: [ネタの要約（1〜2文）]
ネタ軸: [時間軸 / コスト軸 / 不安解消軸 / 体験軸 のいずれか1つ]
フックに使う固有名詞: [腸活/添加物/発酵食品/夜勤/看護師/腸デトックス等を必ず1つ以上]
フックに使う具体的数字: [−10kg/20年/3人/30分/3ヶ月等を必ず1つ以上]
読者の生活インパクト: [この投稿で読者の生活がどう変わるか1文]
角度: [どういう切り口で書くか]
感情フック: [好奇心/共感/驚き/危機感のどれか]
参考バズ投稿: [類似の過去投稿No.（あれば）]
NGワード/注意点: [病院名・居住地・患者特定・医学的断定は禁止]
リサーチ元: [YouTube動画タイトル or ニュース記事タイトル or オーナー実体験]
"""
    return f"""### {slot_label}
推奨ネタ: [ネタの要約（1〜2文）]
ネタ軸: [時間軸 / コスト軸 / 不安解消軸 のいずれか1つ]
フックに使う固有名詞: [Claude Code / ChatGPT / Gemini / OpenClaw 等を必ず1つ以上]
フックに使う具体的数字: [金額・倍数・期間・日数等を必ず1つ以上]
読者の生活インパクト: [この投稿で読者の生活がどう変わるか1文]
角度: [どういう切り口で書くか]
感情フック: [好奇心/共感/驚き/危機感のどれか]
参考バズ投稿: [類似の過去投稿No.（あれば）]
NGワード/注意点: [あれば]
OpenClaw連動: [あり（メイン/誘導）/ なし]
リサーチ元: [YouTube動画タイトル or ニュース記事タイトル]
"""


def load_buzz_posts() -> str:
    """kb_sys_ref_v001.md を読み込む"""
    try:
        with open(BUZZ_POSTS_PATH, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"{BUZZ_POSTS_PATH} not found. Proceeding without buzz history.")
        return "（バズ投稿データなし）"


def generate_briefing(videos: list, news: list, buzz_posts: str, theme: str,
                      performance: dict = None, recycle_candidate: dict = None,
                      snape_insights: str = "", voice_def: str = "") -> str:
    """Gemini Flash でブリーフィングを生成する（タイムアウト・フォールバック付き）"""

    health_mode = is_health_persona(voice_def)
    topic = theme or TOPIC_GENRE or "（指定なし：自動選定してください）"

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
            perf_section += "\n### 直近の個別投稿パフォーマンス（ルーナへの具体的ヒント）\n"
            for p in individual_posts[-9:]:  # 直近9件（3日分）
                er_str = f"{p['engagement_rate']}%" if p.get('engagement_rate') else "-"
                perf_section += (
                    f"- {p['date']} {p['slot']}: "
                    f"いいね{p['likes']} / 閲覧{p['views']} / ER {er_str} / "
                    f"「{p['text_preview']}...」\n"
                )

        perf_section += f"""
→ 【重要】{trend}傾向のパターンを分析し、以下の戦略を取ること：
{"→ 増加しているパターンを継続・強化する。同じ感情フック・形式を別テーマで応用する。" if trend == "増加" else ""}
{"→ 現在のパターンから脱却し、別の感情フック・フォーマット・角度を試す。新しいアプローチを1スロット入れること。" if trend == "減少" else ""}
{"→ 変化をつけるタイミング。既存パターンを1つ維持しつつ、新しい角度を1〜2スロット試す。" if trend == "横ばい" else ""}
{"→ データ蓄積中。多様な角度でテストしながら、反応を見る。" if trend == "不明" else ""}
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

【ルーナへの指示】
- 同じ「核心メッセージ」を保ちながら、以下を全て変える：
  ・フォーマット（体験談→リスト、リスト→対比、等）
  ・導入の形（疑問形→数字、共感→危機感、等）
  ・視点（自分→読者、メリット→デメリット回避、等）
- 同じ言葉・フレーズの繰り返しは厳禁
- このリサイクルスロットはSLOT_2（18時）に使うこと
"""

    if health_mode:
        forbidden_section = """
## 採用禁止のネタ
以下のネタは絶対に選ばないこと：
- ChatGPT / Gemini / OpenClaw / Claude Code 等のAIツール紹介・自動化の話
- Threads運用の仕組み・副業・稼ぐ系の話
- 病院名・居住地・患者特定・医学的断定（治る/効く/必ず痩せる）
- マニアックなベンチマーク比較・抽象的な業界動向論

## 必ず守ること
- 声定義の「看護師20年なのに」定番つかみを全SLOTで使う前提のネタにすること
- オーナーの実体験（夜勤・3人の子・−10kg・添加物・腸活・心のデトックス）を軸にすること
- YouTube/RSSに情報が少なくても、実体験バンクから3スロット別角度でネタを作ること
"""
        slot_footer = "★全スロットで「ネタ軸」「固有名詞」「具体的数字」「読者の生活インパクト」が埋まっていること★"
        youtube_note = "※ keyword フィールドがある動画は設定キーワード（腸活・美容等）でヒットした最新情報です"
        news_label = "## 収集した健康・美容ニュース"
    else:
        forbidden_section = """
## 採用禁止のネタ
以下のネタは絶対に選ばないこと：
- マニアックなベンチマーク比較（Kimi K2/Qwen3/Llama等のモデル比較）
- 抽象的な「AIの将来」「業界動向」論
- 「〇〇とは何か」の解説系（具体的な使い方・体験談でないもの）
- OpenClawを全く含まないスロットが3つとも続く場合
  → 3スロットのうち最低1つはOpenClaw連動とすること
"""
        slot_footer = "★全スロットで「ネタ軸」「固有名詞」「具体的数字」「読者の生活インパクト」「OpenClaw連動」が埋まっていること★"
        youtube_note = "※ keyword フィールドがある動画はキーワード検索「AIエージェント/Claude Code」でヒットした最新情報です"
        news_label = "## 収集したAIニュース"

    voice_section = f"""
## オーナーの声定義（最優先・厳守）
{voice_def[:2500] if voice_def else "（声定義なし）"}
""" if health_mode else ""

    prompt = f"""
あなたはThreads運用のリサーチ・分析担当「{_n('hermione')}」です。
以下のデータをもとに、今日の投稿ライター（{_n('luna')}）向けブリーフィングを作成してください。

## 今日のテーマ方針
{topic}
{voice_section}
## 収集したYouTube最新動画（監視チャンネル＋キーワード検索）
{youtube_note}
{json.dumps(videos, ensure_ascii=False, indent=2)}

{news_label}
{json.dumps(news, ensure_ascii=False, indent=2)}
{perf_section}
{recycle_section}
{f'''## 🔦 スネイプ監視レポートからの改善指示（必ず反映すること）
{snape_insights}
''' if snape_insights else ''}
## 過去のバズ投稿データ（抜粋）
{buzz_posts[:2000]}

---
{forbidden_section}
---
以下のフォーマットでブリーフィングを出力してください。全スロットで全項目を必ず埋めること：

【本日のブリーフィング】

{_briefing_slot_block("SLOT_1（7時・朝投稿）", health_mode)}
{_briefing_slot_block("SLOT_2（18時・夕方投稿）", health_mode)}
{_briefing_slot_block("SLOT_3（21時・夜投稿）", health_mode)}

{slot_footer}
"""

    return call_gemini(prompt, GEMINI_API_KEY)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="", help="今日のテーマ（省略可）")
    args = parser.parse_args()

    logger.info("=== ハーマイオニー リサーチ開始 ===")

    # 月次認証チェック
    try:
        from utils.auth_check import check_auth
    except ImportError:
        from auth_check import check_auth
    is_valid, auth_msg = check_auth()
    if not is_valid:
        logger.error(f"認証エラー: {auth_msg}")
        sys.exit(1)
    logger.info(auth_msg)

    gh = GitHubIssues(GITHUB_TOKEN, GITHUB_REPO)
    issue = gh.get_or_create_today_issue()
    gh.update_pipeline_status(issue.number, "hermione", "running")

    try:
        videos = get_latest_youtube_videos()
        keyword_videos = search_youtube_by_keywords()
        videos = videos + keyword_videos
        news = get_latest_rss_news()
        buzz_posts = load_buzz_posts()
        performance = load_performance_summary()
        recycle_candidate = check_recycle_mode()
        snape_insights = load_snape_insights()

        voice_def = load_voice_definition()
        logger.info(f"声定義ロード: {len(voice_def)}文字, health_mode={is_health_persona(voice_def)}")

        briefing = generate_briefing(
            videos, news, buzz_posts, args.theme, performance,
            recycle_candidate, snape_insights, voice_def,
        )
        logger.info("ブリーフィング生成完了")

        comment_body = f"""## 🔍 {_n('hermione')}より：リサーチ＆分析完了

**実行日時:** {datetime.now().strftime('%Y-%m-%d %H:%M')}

{briefing}

---
*{_n('luna')}、上記ブリーフィングをもとに投稿案3案を作成してください。*
"""
        gh.add_comment(issue.number, comment_body)
        done_ts = datetime.now().strftime("%H:%M")
        gh.update_pipeline_status(issue.number, "hermione", "done", done_ts)
        logger.info(f"GitHub Issue #{issue.number} にコメントを追加しました")

        if recycle_candidate:
            update_recycle_tracker(recycle_candidate["post_no"], recycle_candidate["theme"])

        logger.info("=== ハーマイオニー リサーチ完了 ===")

    except Exception as e:
        logger.error(f"{_n('hermione')}実行失敗: {type(e).__name__}: {e}")
        gh.update_pipeline_status(issue.number, "hermione", "error")
        gh.add_comment(issue.number, f"## ❌ {_n('hermione')}: エラー発生\n\n```\n{type(e).__name__}: {str(e)[:500]}\n```")
        url = os.getenv("DISCORD_WEBHOOK_URL", "")
        if url:
            try:
                requests.post(url, json={"content": f"❌ {_n('hermione')}実行エラー: {type(e).__name__}: {str(e)[:200]}"}, timeout=10)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
