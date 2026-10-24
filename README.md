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
| `what time is it` / `time kya hua` / `aaj kya date hai` | Answers from the PC clock (spoken if TTS is on) |
| `google best laptops` / `what is quantum computing` / `weather in Patna` | Google search in the main window |
| `open gmail` / `open github` / `instagram kholo` / `open example.com` | Opens the site |
| `open notepad` / `launch calculator` / `open my downloads` | Opens an allowlisted app or folder, checks its window appeared |
| `volume 50` / `volume up` / `mute` / `awaaz kam karo` | Sets the speaker volume and reads it back |
| `pause` / `resume` / `next song` | Controls JARVIS's YouTube video (state read back); other players get the media key |
| `scroll down` / `go to the top` / `neeche scroll karo` | Scrolls JARVIS's browser page |
| `play the second video` / `dusra video chalao` | Plays the Nth video visible on the YouTube screen |
| `full screen` / `exit full screen` | YouTube fullscreen on/off |
| `rotate screen` / `rotate screen back` | Rotates the display, only after you approve |
| `open camera` / `open android studio` / `sticky notes kholo` | Any Start-menu app (say "app" for names that are also sites: `open whatsapp app`) |
| `set a timer for 5 minutes` / `remind me in 20 minutes to drink water` | Timer; speaks and shows a notification when done (lost if JARVIS restarts) |
| `take a screenshot` | PNG in `data\screenshots\` |
| `directions to india gate` / `restaurants near me` / `headphones on amazon` | Google Maps / store search |
| anything new | LLM plans it, validated against the tool list; offered for saving if every step verifies |

## Desktop app (self-updating)

```powershell
.\stop.ps1                      # if JARVIS is running from this folder
powershell -ExecutionPolicy Bypass -File .\install-app.ps1
```

This installs a separate copy of `main` at `D:\Apps\JARVIS` (data: `D:\Apps\JARVIS-data`) and adds
**JARVIS** to the Start menu and Desktop. It opens in its own window; closing the window stops JARVIS.

Updating: merge into `main` and push to GitHub. In the app, open **Updates** (top bar) >
**Check for updates** > **Update now** > **Restart now**. It only fast-forwards a clean `main`,
reinstalls Python packages if a requirements file changed, and rebuilds the dashboard if `frontend/`
changed; if a step fails, the code is put back as it was.

## Voice

- Say **"Hello Archu"**, wait for the ting, then the command, or say both at once: "Hello Archu, open gmail". On/off and the voice (Swara, Neerja, Heera, Zira) are in the top bar. Online voices send the spoken text to Microsoft's speech service; Heera needs Settings > Time & language > Speech > Add voices > English (India).
- The microphone is processed on this PC only (faster-whisper). Voice extras: `install.ps1 -Voice` (requirements-voice.txt).

## Supported

- Tools: `open_url`, `search_youtube`, `play_youtube_result`, `open_leetcode_problem`, `open_claude`, `get_problem_summary`, `arrange_windows`, `get_active_window`, `verify_workspace`, `create_notion_page`, `create_notion_db_entry`, `speak`, `ufo_desktop_task`, plus everyday tools `web_search`, `open_site`, `open_app`, `tell_time`, `media_key`, `set_volume`, `scroll_page`, `play_visible_video`, `video_fullscreen`, `rotate_screen` (approval), `set_timer`, `take_screenshot` (fixed allowlists or Start-menu apps, no shell).
- 14 seed workflows with English + Hinglish patterns, so everyday commands run locally with zero LLM calls. `backend/tests/test_daily_routing.py` lists every phrasing that is guaranteed to route locally. Seeds changed in code are re-saved as a new version on startup.
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
