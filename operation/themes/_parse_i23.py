import json
import subprocess
from pathlib import Path

raw = subprocess.check_output(
    ["gh", "api", "repos/umesayu7788-ctrl/hogwarts-2026/issues/23/comments?per_page=100"],
    text=True,
    encoding="utf-8",
)
d = json.loads(raw)
packs = [
    c
    for c in d
    if c.get("user", {}).get("login") == "github-actions[bot]"
    and "承認申請" in c.get("body", "")
    and "推奨投稿案" in c.get("body", "")
]
print("packs", len(packs))
if not packs:
    # fallback: any malfoy approval-like
    packs = [
        c
        for c in d
        if c.get("user", {}).get("login") == "github-actions[bot]"
        and "承認申請" in c.get("body", "")
    ]
    print("approval_only", len(packs))
if packs:
    latest = packs[-1]
    print("created", latest["created_at"])
    Path("operation/themes/_tmp_issue23_approval_latest.md").write_text(
        latest["body"], encoding="utf-8"
    )
    print("saved")
else:
    print("NONE")
    for c in d[-6:]:
        print(c["created_at"], c["user"]["login"], c["body"][:80].replace("\n", " "))
