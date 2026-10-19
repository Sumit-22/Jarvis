# JARVIS progress

## Environment (from M0)
- Build machine for this first pass: a Linux cloud container (Python 3.13, Node 22), not the target laptop.
- Target laptop (Acer Aspire 3, i5 11th gen): **not inspected yet.** Run `.\inspect.ps1` on it and paste the output here.
- Windows: ... | CPU: ... | RAM: ... | Free disk: ...
- Python: ... | Node: ... | Git: ... | PowerShell: ... | Execution policy: ...

## UFO (from the repo's own docs)
- Repo: https://github.com/microsoft/UFO, commit read: `eae3c0a8d168c47cb10df0652e293e092eda1078`
- Python: 3.10 or 3.11 (README badge)
- Install: `pip install -r requirements.txt` in its own venv (`vendor\UFO\.venv`)
- Config: `copy config\ufo\agents.yaml.template config\ufo\agents.yaml`, then fill API_TYPE / API_BASE / API_KEY / API_MODEL (user does this)
- Launch (UFO²): `python -m ufo --task <task_name> -r "<request>"` (documented in `documents/docs/getting_started/quick_start_ufo2.md`); logs go to `logs/<task_name>/`

## Milestones
| Milestone | Status | Date | Notes |
|---|---|---|---|
| M0 Inspect | blocked on user | 2026-10-19 | UFO docs read and recorded; laptop values need `inspect.ps1` |
| M1 Skeleton + scripts | code done, UNTESTED on Windows | 2026-10-19 | install/start/stop.ps1 written; no PowerShell was available to run them |
| M2 Registry/router/executor | done | 2026-10-19 | pytest: all M2 acceptance tests pass (mocked) |
| M3 Browser + window tools | code done, smoke run UNTESTED | 2026-10-19 | unit tests pass with Playwright/pywin32/UFO mocked; needs the manual smoke run on Windows |
| M4 Dashboard | built, partly verified | 2026-10-19 | verified in headless Chromium against a dry-run backend: live steps, approval dialog, local route; Stop < 2s verified in pytest |
| M5 Notion + real planner | code done, blocked on user | 2026-10-19 | mocked tests pass; needs keys in .env and a real run |
| M6 Voice + TTS | code done, UNTESTED | 2026-10-19 | needs `install.ps1 -Voice` and a mic |
| M7 UFO in planner | code done, real UFO UNTESTED | 2026-10-19 | tested against a stub UFO subprocess only |

## Last session
- Changed: whole codebase (backend, dashboard, scripts, tests).
- Tests: 53 passed, 0 failed (`cd backend; .venv\Scripts\python -m pytest`), on Linux/Python 3.13.
- Frontend: `npm run build` passes (tsc + vite).
- Manually verified (dry run, headless Chromium on Linux): dashboard loads, "open my coding workspace for two-sum" routes locally with 0 planner calls, missing slug asks the user, Notion step shows the approval dialog and waits.
- UNTESTED: everything that touches Windows (pywin32, real Chromium windows, window layout), real YouTube/LeetCode/claude.ai pages, real Notion, real LLM API, real UFO, faster-whisper, pyttsx3, all .ps1 scripts.

## Blocked on user
- [ ] Install prerequisites if missing: Python 3.11 (works for both JARVIS and UFO), Node 20+ LTS, Git
- [ ] Copy this folder to `C:\Jarvis`, run `powershell -ExecutionPolicy Bypass -File .\install.ps1`
- [ ] Fill `.env` (LLM_API_KEY etc.) and `vendor\UFO\config\ufo\agents.yaml` yourself
- [ ] Run `.\inspect.ps1` and paste output into the Environment section

## Next action
- On the laptop: finish M0/M1 acceptance (install twice, start, health 200, stop, one UFO Notepad task), then the M3 smoke run.
