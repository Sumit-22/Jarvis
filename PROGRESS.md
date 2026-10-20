# JARVIS progress

## Environment (from M0)
- Build machine for this first pass: a Linux cloud container (Python 3.13, Node 22), not the target laptop.
- Target laptop: inspected 2026-10-20 with `inspect.ps1` (repo at `D:\Github Projects\GitHub\Jarvis`, not `C:\Jarvis`).
- Windows: Windows 11 Home Single Language 10.0.26200 (build 26200) | CPU: 11th Gen Intel Core i5-1135G7 @ 2.40GHz | RAM: 7.8 GB | Free on C: 7.4 GB
- Python (py -0p): 3.14 (default) `C:\Users\USER\AppData\Local\Python\pythoncore-3.14-64\python.exe`, 3.12 `C:\Users\USER\AppData\Local\Programs\Python\Python312\python.exe`; **no 3.11**
- Node: not found | npm: not found | Git: 2.46.2.windows.1 | PowerShell: 5.1.26100.8457
- Execution policy: MachinePolicy/UserPolicy/CurrentUser/LocalMachine Undefined, Process Bypass (from `-ExecutionPolicy Bypass`)
- UFO: not cloned yet

## UFO (from the repo's own docs)
- Repo: https://github.com/microsoft/UFO, commit read: `eae3c0a8d168c47cb10df0652e293e092eda1078`
- Python: 3.10 or 3.11 (README badge)
- Install: `pip install -r requirements.txt` in its own venv (`vendor\UFO\.venv`)
- Config: `copy config\ufo\agents.yaml.template config\ufo\agents.yaml`, then fill API_TYPE / API_BASE / API_KEY / API_MODEL (user does this)
- Launch (UFO²): `python -m ufo --task <task_name> -r "<request>"` (documented in `documents/docs/getting_started/quick_start_ufo2.md`); logs go to `logs/<task_name>/`

## Milestones
| Milestone | Status | Date | Notes |
|---|---|---|---|
| M0 Inspect | done | 2026-10-20 | `inspect.ps1` run on the laptop, output above |
| M1 Skeleton + scripts | done (UFO task UNTESTED) | 2026-10-20 | install.ps1 run 1 failed on UFO `pandas==1.4.3` (no py3.11 wheel, sdist needs pkg_resources); fixed by installing from a patched copy pinning pandas==1.5.3. Run 2 exit 0, run 3 exit 0 in 86s with nothing recreated (idempotent). start.ps1 -> /api/health 200, stop.ps1 -> backend stopped, health unreachable, pids.json removed |
| M2 Registry/router/executor | done | 2026-10-20 | pytest 53 passed on Windows |
| M3 Browser + window tools | done | 2026-10-20 | real smoke run: YouTube /watch reached (playing, not paused); workspace LeetCode left [0,0,768,816], Claude right [768,0,1536,816] on 1536x816 work area, verify_workspace passed; no windows.py changes needed |
| M4 Dashboard | built, partly verified | 2026-10-20 | `npm run build` passes on Windows (Node 24.22.0); served by backend at :8765; UI not re-clicked through on Windows |
| M5 Notion + real planner | code done, blocked on user | 2026-10-20 | "open claude" routed to the LLM; Anthropic returned 400 "credit balance is too low", shown cleanly as an error. Needs API credits. Notion not run |
| M6 Voice + TTS | STT done, TTS UNTESTED | 2026-10-20 | `install.ps1 -Voice` OK; faster-whisper 1.2.1 broke with PyAV 19 (`open() got an unexpected keyword argument 'metadata_errors'`), pinned `av==14.2.0`. POST /api/voice with a SAPI-generated WAV: transcript "Play a video about Python decorators." in 3.94s, then youtube_play ran locally and verified. Real mic via dashboard button not tried; TTS output not checked |
| M7 UFO in planner | code done, real UFO UNTESTED | 2026-10-20 | UFO installed (vendor\UFO, Python 3.11.9 venv) but agents.yaml not filled, so the Notepad task was not run |

## Last session (2026-10-20, Windows laptop)
- Repo lives at `D:\Github Projects\GitHub\Jarvis` (not `C:\Jarvis`); scripts use `$PSScriptRoot`, so this works.
- Installed per-user on D: (user asked): Node v24.22.0 portable at `D:\Tools\nodejs` (SHA256 verified, added to user PATH), Python 3.11.9 at `D:\Tools\Python311` (signed installer, per-user, registered with `py -3.11`). JARVIS backend venv uses Python 3.12.
- User env vars to keep C: free: `PLAYWRIGHT_BROWSERS_PATH=D:\Tools\ms-playwright`, `PIP_CACHE_DIR=D:\Tools\cache\pip`, `npm_config_cache=D:\Tools\cache\npm`.
- Changed: `install.ps1` (UFO pandas pin workaround).
- Tests: 53 passed, 0 failed (`cd backend; .venv\Scripts\python -m pytest -q`, 14.9s), Windows / Python 3.12.
- Smoke (POST /api/command?wait=true):
  - "play a video about python decorators": route local, youtube_play, search 10 results, /watch?v=PTBZ674EsvI, has_video, not paused.
  - "open my coding workspace for two-sum" x2 (plus one earlier run to open the windows): route local via pattern, all 4 steps verified both times; /api/usage planner_calls 0 -> 0 -> 0, cache_hits 3 -> 4.
- Observed: on the 2nd workspace run claude.ai redirected the side window to `/login?from=logout&reauth=1` (session logged out by claude.ai). open_claude still verifies as passed and reports `needs_login: true`.
- UNTESTED: real LLM planner route, Notion, UFO task, voice/TTS, dashboard UI clicks on Windows, multi-monitor.

- Login: Google / claude.ai refuse sign-in inside the Playwright-driven windows. Added `login.ps1`: with JARVIS stopped it opens the same profiles (`data\profiles\main`, `side`) in Playwright's Chromium without automation for a normal manual login, then waits for the windows to close. User logged in this way; persistence on claude.ai not yet re-checked (only the workspace workflow opens Claude, and the user asked not to run LeetCode for now).
- `HF_HOME=D:\Tools\cache\huggingface` (user env var) so the whisper model is on D:.

## Blocked on user
- [ ] Add Anthropic API credits (planner returns "credit balance is too low")
- [ ] Check claude.ai stays logged in (user asked to skip LeetCode, so the workspace test was not re-run)
- [ ] Fill `vendor\UFO\config\ufo\agents.yaml` (OpenAI/Azure key) or set `UFO_ENABLED=false` in `.env`
- [ ] Notion values in `.env` if Notion is wanted

## Next action
- Run one UFO Notepad task once agents.yaml is filled; send one new command to exercise the real planner; check claude.ai login persistence.
