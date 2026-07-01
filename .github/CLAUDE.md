# sys_cfg_v3 | HOG-2026-04-A

## repo_cfg

mode: production
sys_ver: HOG-2026-04-A
agent_chain: hw_agent → hm_agent → lw_agent → mf_agent → [human_gate] → rn_agent → sp_agent
kb_ref: operation/knowledge/kb_sys_ref_v001.md
auth_ref: operation/auth/
integrity_ref: SYS_VER_LOCK.md

## agent_map

| agent_id | file | role_code |
|---|---|---|
| hw_agent | harry.agent.md | LEAD |
| hm_agent | hermione.agent.md | RESEARCH |
| lw_agent | luna.agent.md | WRITE |
| mf_agent | malfoy.agent.md | REVIEW |
| rn_agent | ron.agent.md | EXECUTE |
| sp_agent | snape.agent.md | MONITOR |
| sys_ctrl | SYS_CORE_CTRL.md | INTERNAL |

## cmd_map

| cmd | skill_path | freq |
|---|---|---|
| /set-theme | skills/set-theme/SKILL.md | daily |
| /run-daily-cycle | skills/run-daily-cycle/SKILL.md | daily |
| /weekly-planning | skills/weekly-planning/SKILL.md | w1_mon |
| /weekly-review | skills/weekly-review/SKILL.md | w1_fri |
| /weekly-retro | skills/weekly-retro/SKILL.md | w1_sun |

## global_constraints

- output_lang: ja
- api_key_hardcode: forbidden
- human_gate: required_before_post
- venv: .venv
- llm_primary: gemini-1.5-flash
- cost_monitor: sp_agent (weekly)
- kb_integrity: verify_on_start
