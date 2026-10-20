# JARVIS

A local Windows assistant that turns plain-language commands into verified, repeatable workflows. A command that matches a saved workflow runs with **zero LLM calls**; only new commands go to the LLM planner, and a plan that worked can be saved (with your consent) so next time it runs for free.

Full spec: `JARVIS_SPEC.md`. Current status: `PROGRESS.md`.

## Setup (Windows, no admin)

1. Install, if missing: **Python 3.11** (https://www.python.org/downloads/windows/, keep "py launcher" ticked), **Node.js 20+ LTS** (https://nodejs.org/), **Git** (https://git-scm.com/download/win). Python 3.11 works for both JARVIS and Microsoft UFO.
2. Put this folder at `C:\Jarvis`.
3. In PowerShell (not admin):
   ```powershell
   cd C:\Jarvis
   powershell -ExecutionPolicy Bypass -File .\install.ps1          # add -Voice for speech input, -SkipUfo to skip UFO
   ```
4. Open `C:\Jarvis\.env` and fill `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY` (and the Notion values if you want Notion). Never paste keys in chat.
5. If you use UFO: open `vendor\UFO\config\ufo\agents.yaml` and fill its API settings yourself.
6. Start / stop:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\start.ps1     # opens http://127.0.0.1:8765
   powershell -ExecutionPolicy Bypass -File .\stop.ps1
   ```
   `start.ps1 -Dev` also runs the Vite dev server on http://127.0.0.1:5173.
7. First run: log in to YouTube/Google, LeetCode and claude.ai **once, by hand**. Google and claude.ai refuse sign-in inside the automated windows, so with JARVIS stopped run `powershell -ExecutionPolicy Bypass -File .\login.ps1`: it opens the same two profiles (`main` and `side`) without automation; log in, then close both windows. The profiles live in `data\profiles\` and keep the logins.

Without an API key JARVIS still runs every saved workflow; only new commands (the LLM route) are unavailable.

## Try it

| Say / type | What happens |
|---|---|
| `open my coding workspace for two-sum` | LeetCode left, Claude right, layout verified. Local, 0 LLM calls |
| `open my coding workspace` | Asks which problem (no LLM) |
| `play a video about python decorators` | YouTube search, plays first result. Local |
| `meeting notes titled Standup notes shipped M4` | Notion page, after you approve in the dialog |
| `repeat the last workflow` / `repeat what we did yesterday` | Re-runs from history |
| anything new | LLM plans it, validated against the tool list; offered for saving if every step verifies |

## Supported

- Tools: `open_url`, `search_youtube`, `play_youtube_result`, `open_leetcode_problem`, `open_claude`, `get_problem_summary`, `arrange_windows`, `get_active_window`, `verify_workspace`, `create_notion_page`, `create_notion_db_entry`, `speak`, `ufo_desktop_task`.
- Approvals for anything that sends data out or uses UFO; Stop button; dry run (`DRY_RUN=true`); usage panel (planner calls, cache hits/misses, tokens, cost).
- Cost is only estimated if you set `LLM_INPUT_COST_PER_MTOK` / `LLM_OUTPUT_COST_PER_MTOK`; otherwise it shows as unknown, never as zero.

## Not supported

- No shell/command tool, by design. No reading of cookies or passwords.
- Multi-monitor layouts beyond "the monitor the window is on".
- UFO workflows are never free: every run calls UFO's LLM and is flagged in the UI.

## Development

```powershell
cd backend; .venv\Scripts\python -m pytest     # all external calls mocked
cd frontend; npm run build
```
Logs: `data\logs\*.jsonl` (secrets redacted). Database: `data\jarvis.db`.

## Troubleshooting

- **Script blocked by execution policy**: use `powershell -ExecutionPolicy Bypass -File .\install.ps1`, or run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` yourself.
- **Backend did not become healthy**: read `data\logs\backend.err.log`.
- **"window not found" in arrange_windows**: the page title didn't contain `LeetCode` / `Claude` yet (login or Cloudflare page). Log in once in that window and retry.
- **LeetCode "cloudflare wall"**: solve the check by hand in the main window; JARVIS never bypasses it.
- **YouTube video paused**: Chrome autoplay policy; press play. The step reports this instead of pretending.
- **Planner says no LLM configured**: fill `.env` and restart (`stop.ps1`, `start.ps1`).
- **UFO step fails**: check `vendor\UFO\config\ufo\agents.yaml` and the UFO log folder shown in the tool activity panel.
