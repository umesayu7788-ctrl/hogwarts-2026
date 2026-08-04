# temporary helper: post approved SLOT text to Threads + issue comment
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def create_container(user_id: str, token: str, text: str, reply_to: str | None = None) -> str:
    url = f"https://graph.threads.net/v1.0/{user_id}/threads"
    data = {
        "media_type": "TEXT",
        "text": text,
        "access_token": token,
    }
    if reply_to:
        data["reply_to_id"] = reply_to
    r = requests.post(url, data=data, timeout=60)
    r.raise_for_status()
    cid = r.json().get("id")
    if not cid:
        raise RuntimeError(f"no container id: {r.text}")
    return cid


def publish(user_id: str, token: str, creation_id: str) -> str:
    url = f"https://graph.threads.net/v1.0/{user_id}/threads_publish"
    r = requests.post(
        url,
        data={"creation_id": creation_id, "access_token": token},
        timeout=60,
    )
    r.raise_for_status()
    pid = r.json().get("id")
    if not pid:
        raise RuntimeError(f"no post id: {r.text}")
    return pid


def post_tree(user_id: str, token: str, parts: list[str]) -> tuple[str, list[str]]:
    root = None
    reply_ids: list[str] = []
    parent = None
    for i, text in enumerate(parts):
        cid = create_container(user_id, token, text, reply_to=parent)
        time.sleep(2)
        pid = publish(user_id, token, cid)
        if i == 0:
            root = pid
            parent = pid
        else:
            reply_ids.append(pid)
            parent = pid
        time.sleep(3)
    assert root
    return root, reply_ids


def add_issue_comment(token: str, repo: str, issue: int, body: str) -> None:
    url = f"https://api.github.com/repos/{repo}/issues/{issue}/comments"
    r = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json={"body": body},
        timeout=60,
    )
    r.raise_for_status()


SLOT2_PARTS = [
    "水素水、開封したら早めに飲んだ方がいいらしいよ。水素って逃げやすいから、翌日にはほぼ残ってない、みたいな話もあるんだ。",
    "私は飲んでみて「続けたい」って思ったタイプ。高いから毎日じゃなくてもいいし、普通の水分補給がまず大事だと思ってるよ。完璧じゃなくていいから、続く形がいちばん大事。夜勤のある生活でも、無理なく取り入れられるのがポイントだよね🥗✨",
    "水素水やってるママさんいる？一緒にゆるく整えよ🙌 フォローすると、腸活と水まわりの小さなヒントをシェアするよ。過度な期待はせず、自分のペースで続けられる話を届けるね。",
]

SLOT3_PARTS = [
    "健康飲料って、買うと安心した気になる日あるよね。私も水素水を試してみて、続けたいなって思った。",
    "でもいちばん大事なのは、効能の断定じゃなくて、食事・うんち・水まわりをゆるく整える意識だと思う。完璧ゼロを目指すより、続く方。体感で選んで、あとはゆるく続ける。一緒にゆるく整えよ💩",
]


def main() -> int:
    slot = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    env = load_env()
    token = env.get("THREADS_ACCESS_TOKEN", "")
    user_id = env.get("THREADS_USER_ID", "")
    gh_token = env.get("GITHUB_TOKEN", "")
    repo = env.get("GITHUB_REPO", "")
    if not token or not user_id:
        print("THREADS credentials missing")
        return 1
    parts = SLOT2_PARTS if slot == 2 else SLOT3_PARTS
    label = "🌆 18時・夕方投稿" if slot == 2 else "🌙 21時・夜投稿"
    marker = "SLOT_2" if slot == 2 else "SLOT_3"
    root, replies = post_tree(user_id, token, parts)
    full = "\n===THREAD===\n".join(parts)
    body = (
        f"## 📤 大毅より：{label} 投稿完了\n\n"
        f"<!-- {marker} 投稿完了 -->\n\n"
        f"**投稿日時:** {time.strftime('%Y-%m-%d %H:%M')}\n"
        f"**投稿ID:** `{root}`\n"
        + (f"**ツリー返信ID:** {', '.join(f'`{x}`' for x in replies)}\n" if replies else "")
        + f"\n**投稿テキスト:**\n```\n{full}\n```\n\n**ステータス:** 投稿成功（水素水・オーナー確定文）\n"
    )
    if gh_token and repo:
        add_issue_comment(gh_token, repo, 24, body)
    print(json.dumps({"slot": slot, "post_id": root, "replies": replies}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
