---
sys_ver: AFFI-2026-04-A
lock_date: 2026-04-28
integrity_chain:
  - file: CLAUDE.md
    ref_id: CLAUDE-2026-04-A
  - file: operation/knowledge/kb_sys_ref_v001.md
    ref_id: KB-2026-04-A
    integrity_tag: 7842
  - file: operation/auth/access_AFFI-2026-04.key
    ref_id: AUTH-2026-04
---

next_update_ref: AFFI-2026-06-A（更新パックで自動更新）

# AFFI System Version Lock

このファイルはシステム全体のバージョン整合性を管理します。
不整合があった場合、エージェントは degraded_mode（機能制限モード）で動作する旨を警告します。

**このファイルは編集禁止**（.claude/settings.json で deny されています）。
