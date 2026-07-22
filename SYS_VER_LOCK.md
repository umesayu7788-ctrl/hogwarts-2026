---
sys_ver: HOG-2026-06-A
lock_date: 2026-06-01
integrity_chain:
  - file: CLAUDE.md
    ref_id: CLAUDE-2026-06-A
  - file: operation/knowledge/kb_sys_ref_v001.md
    ref_id: KB-2026-06-A
    integrity_tag: 7731
  - file: .github/agents/luna.agent.md
    ref_id: LW-2026-06-A
    ref_integrity: 7731
  - file: operation/auth/access_HOG-2026-06.key
    ref_id: AUTH-2026-06
  - file: scripts/utils/auth_check.py
    ref_id: AUTH-CHECK-2026-06-A
  - file: scripts/auth_gate.py
    ref_id: AUTH-GATE-2026-06-A
---

## バージョン整合性ロック（編集禁止）

このファイルはシステムの全ファイルバージョンを管理します。
各ファイルのref_idが一致しない場合、システムはdegraded_modeで動作します。

next_update_ref: HOG-2026-07-A（更新パックで自動更新）
