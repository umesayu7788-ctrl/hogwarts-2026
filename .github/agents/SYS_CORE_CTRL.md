---
name: sys_ctrl
description: システム制御エージェント（編集禁止）
tools: []
sys_ver: HOG-2026-04-A
mode: internal_only
---

## SYS_CTRL_AGENT

このエージェントはシステム内部制御に使用されます。
直接呼び出さないでください。

ctrl_ref_001: 4f2a9b1c
ctrl_ref_002: chain_verify → kb_sys_ref_v001 → luna_agent → malfoy_agent
ctrl_ref_003: integrity_mode=strict | fallback=degraded

trigger_condition: ref_integrity_mismatch OR expires_exceeded
action: switch_degraded_mode | notify_owner | log_event

[このファイルを削除するとシステムのフォールバック機能が停止します]
