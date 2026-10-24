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
- Dashboard mic button: hold-to-talk raced getUserMedia (release before the mic opened = nothing sent, recorder stuck). Changed to click-to-start / click-to-stop in `frontend/src/App.tsx`; build passes. Real mic UNTESTED.
- Added `LLM_BASE_URL` (OpenAI-compatible endpoint for `LLM_PROVIDER=openai`) so the planner can use free Gemini / Groq / local Ollama. 56 tests pass. Real call UNTESTED (user to add a free key).
- `start.ps1` now copies the user env vars `PLAYWRIGHT_BROWSERS_PATH` / `HF_HOME` into the backend process if the calling shell lacks them (a stale shell made Playwright look for Chromium on C: and fail). `play_youtube_result` waits up to 10s for results before failing (one run on the first launch after that error found none). YouTube command then passed 2/2 via the API.

## Session 2026-10-21 (Windows laptop): everyday commands + dashboard redesign
- Added `backend/jarvis/tools/daily.py`: `web_search`, `open_site`, `open_app`, `tell_time`, `media_key`, `set_timer`, `take_screenshot` (allowlisted targets only, no shell). Added `pillow==12.3.0` for screenshots.
- 11 new seed workflows (directions, maps_search, media_control, open_app, open_site, set_timer, site_search, take_screenshot, tell_time, weather, web_search) with English + Hinglish patterns; `youtube_play` got more patterns. `seed()` now re-saves a seed as a new version when its definition changed (old row kept, patterns replaced).
- Fuzzy alias guard: a token_set hit whose alias is only a small subset of the command (token_sort < 60) now asks to confirm instead of running.
- A step can return `say` (e.g. the time); it is shown in the chat, sent in `run_finished`, and spoken instead of "Done.".
- Browser: if the user closed a Playwright window, `page()` now drops the dead context and relaunches once (one smoke run failed with TargetClosedError before this fix).
- Dashboard redesigned (glass panels, Siri-style orb, quick actions, animated step timeline, cache-hit ring, timer toasts, mobile layout). `npm run build` passes; checked with headless screenshots at 1440x900 and 390x844 (no horizontal scroll, no console errors).
- Tests: 161 passed, 0 failed (`backend\.venv\Scripts\python -m pytest -q`), incl. 88 everyday phrasings in `tests/test_daily_routing.py`.
- Real smoke run via POST /api/command?wait=true: 42 everyday commands (time, date, gmail, github, google, questions, weather, directions, near me, amazon, wikipedia, notepad, calculator, paint, downloads, explorer, settings, vs code, volume up/down, mute/unmute, pause/resume/next, screenshot, 10 s timer, 1 min reminder, YouTube x3, whatsapp, instagram, chatgpt, youtube music, repeat last). 41 succeeded first time; the failure was the TargetClosedError above and passed after the fix. Planner calls stayed at 1 (no new LLM calls).
- UNTESTED: media keys only confirm the key was sent (no read-back); timer toast in the real UI (backend event verified by unit test, the 10 s timer ran but the UI was not watched); word/excel/powerpoint/camera/clock/store apps not launched.

## Session 2026-10-22: volume read-back, scroll, Nth video, fullscreen, rotate, any app
- Volume now goes through Windows Core Audio (`pycaw==20260927`): up/down = 10% steps, mute/unmute explicit, `set_volume` to an exact %; each run reads the level back and verification fails if it did not change.
- Play/pause/next/previous control JARVIS's YouTube page directly (video.paused / URL read back); media keys only when that page has no video.
- New tools: `scroll_page` (scrollY read back), `play_visible_video` (Nth video visible on the YouTube screen, video id read back), `video_fullscreen` (trusted "f" key, document.fullscreenElement read back), `rotate_screen` (ChangeDisplaySettingsEx, approval required every time, orientation read back).
- `open_app` also opens any Start-menu app (Get-StartApps at startup, cached in `data\start_apps.json`; names that are also websites need "app", e.g. "open whatsapp app"); verified by window title or a new window. `camera on karo` etc. route to the Camera app.
- Bug fixed: TTS (pyttsx3 runAndWait) hung after many runs, blocking the command response and holding the audio device. TTS now runs on one SAPI thread, never awaited by a run; commands return in ~0.5 s.
- Tests: 207 passed, 0 failed.
- Real run on the laptop (all routed locally, planner calls stayed 1): volume 50/down/kam karo/up/mute/unmute/30%/90% each read back; YouTube pause/resume (video state read back), full screen on/off x2, scroll down/up (scrollY 0->654->1309->654), "play the second video" and "dusra video chalao" on a watch page, "play the 1st video" on the YouTube home page, "next song", Google results scroll (0->1309->1963->1309); open camera, character map, sticky notes, sound recorder, whatsapp app; rotate screen -> portrait and back -> landscape (auto-approved by the test script through /api/approve). 30/30 succeeded after the TTS fix; before it, "exit full screen" itself succeeded but the response hung on TTS.
- UNTESTED: rotation approved by clicking in the real dashboard; mouse-wheel fallback when JARVIS's browser is closed; play/pause of other players (Spotify etc.) is a media key with no read-back.

## Session 2026-10-22 (cont.): Claude bridge
- `backend/jarvis/tools/claude_bridge.py`: `claude_ask`, `claude_status`, `claude_stop`. "claude code pe jao aur <task>", "claude ko bolo ki ...", "ask claude to ...", "new chat on claude: ...", with optional "plan mode" / "auto mode", "using opus", "in the <name> project". Approval dialog shows the exact text, folder, mode and session before anything is sent (`CLAUDE_CONFIRM_SEND=true`); `claude_ask` is never retried.
- Claude Code target: runs the CLI (`claude -p --output-format stream-json`, prompt on stdin, bundled VS Code binary found automatically) in the background, streams steps/files to the dashboard's Claude card, resumes the same session for follow-ups, records cost under purpose `claude_code`. Modes: plan, manual, acceptEdits (default), auto, dontAsk; bypassPermissions is rejected.
- When Claude finishes, JARVIS speaks and shows the answer itself: Claude Code is told to end with an `ANSWER:` line (the answer to the question, or what is now done); without it, a short reply is used whole, else its first paragraph. Full reply is under "Full reply" in the card.
- claude.ai target: code written (side window, composer, send, waits for the stop button to go and the reply to settle) but UNTESTED: the side profile is logged out of claude.ai again (`/login?from=logout&reauth=1`), so the logged-in page structure could not be checked.
- `strip_fillers` now removes "Jarvis" only as a call at the start/end, so "the jarvis project" survives in prompts.
- Tests: 236 passed, 0 failed.
- Live: one Claude Code run through JARVIS (approved by the test script): sent in 6 s, progress streamed, finished, summary spoken, cost $0.18 recorded. A denied approval sent nothing. That run was before the ANSWER: change; the follow-up/resume and plan-mode runs were not done live (user stopped the test), only with a faked CLI.

- Bug found in the live check (2026-10-22): Claude Code answered correctly (with the ANSWER: line, seen in its session file), but JARVIS's stream reader died on a ~95 KB stream-json line (asyncio's 64 KB readline limit), so the job stayed "running" and "is claude done" kept saying "still working". Fixed: 64 MB line limit; any reader error now marks the job failed instead of leaving it running. Regression test with a real child process and a 100 KB line (fails with the old limit, passes now). 238 tests pass. Two test prompts reached Claude Code during that check even though the tool calls showed as rejected.

## Session 2026-10-22 (cont.): Indian voice + "Hello Archu" wake word
- Voices, chosen in the dashboard (top bar > Voice / Hello Archu): Swara (hi-IN, neural, online via edge-tts 7.3.1), Neerja (en-IN, neural, online), Heera (en-IN, offline, WinRT OneCore; needs the "English (India)" voice pack, not installed on this laptop), Zira (offline). Default Swara. If the chosen voice fails, the next offline voice speaks and the panel says why. Choice stored in `data\prefs.json`. Each voice has a Test button.
- TTS now one worker thread; edge-tts mp3 played with Windows MCI, OneCore wav with winsound. All 3 engines played on this laptop (MCI/winsound return codes; I cannot hear them).
- Wake word: `jarvis/voice/wake.py`, mic via sounddevice 0.5.6, audio stays local. Energy segmenter -> whisper `tiny` (wake check) -> fuzzy "archu" match; command transcribed with `base`. "Hello Archu" alone -> chime, JARVIS's YouTube video paused and volume lowered to a third, next utterance is the command (8 s window), then media restored before the command runs. "Hello Archu, <command>" in one breath runs it directly. Mic ignored while JARVIS speaks.
- Found by measuring: a whisper prompt makes it "hear" the wake phrase in noise (4/10 noise clips woke it). With whisper's VAD + dropping low-confidence segments: tiny and base both 15/15 wakes, 0 false wakes on speech or 10 noise clips (synthetic Indian voices). tiny 0.74 s vs base 1.15 s per clip.
- Real use on the laptop (user's own voice, before the tiny/ducking change): "Hello Archu." woke it and the next command played a YouTube video; "I Archu." also woke it, but with YouTube playing the command took 35 s to transcribe and came out empty (CPU busy with Playwright's software video rendering) -> the pause/duck + tiny model change. The new version is UNTESTED with a real voice.
- Tests: 262 passed, 0 failed.

## Session 2026-10-24: YouTube skip ad + Hinglish play/pause
- New tool `skip_ad` (`tools/daily.py`) + workflow `skip_ad`: "skip ad", "skip the ad", "ad skip karo", "ad hatao"... Works on JARVIS's own YouTube window: real click on YouTube's Skip button (waits up to 8 s for it), reads back `.ad-showing`. No ad -> pass ("No ad is playing."); unskippable ad -> verification fails with that reason. Plain "skip" still means next track.
- More pause/play phrases: "video pause karo", "youtube play karo", "pause kar do", "play karo", "wapas chalao", "pause the youtube video".
- `play_youtube_result`: seen 4 times right after a JARVIS start — results page had 0 links on the click step though the search step counted them. Not reproducible standalone. Now reloads the results page once before failing; error includes the page URL and tab count.
- Planner now on Gemini (`LLM_PROVIDER=openai`, `LLM_BASE_URL`, `gemini-3.5-flash`; `gemini-2.5-flash` is closed to new keys, `3.8-flash` was returning 503).
- Live on the laptop: play arijit singh songs -> skip ad ("ad skipped", a real ad) -> video pause karo (paused, read back) -> play karo (playing, read back). All succeeded first attempt.
- Tests: 281 passed, 0 failed.

## Session 2026-10-24 (cont.): play-failure fix + performance pass
- Root cause of "No such result on the page" after a fresh start: `play_youtube_result` re-read the results DOM, which YouTube sometimes re-renders after `search_youtube` counted it. Now `search_youtube` caches the result hrefs (`ctx.youtube_results`, keyed by URL) and play uses them; reads only the visible `ytd-search` (YouTube keeps hidden old pages in the DOM).
- Speed changes (measured on this laptop, real YouTube):
  - play step: clicks the result inside the loaded page (SPA) instead of a full page load, and polls until the video moves instead of a fixed 2.5 s sleep: 5.8-8.7 s -> 1.0-3.3 s.
  - search step: when YouTube is already open, types into YouTube's search box (no page load), waits until results differ from the previous search; falls back to the URL load: 3-4.3 s -> 1.7-2.9 s.
  - pause/play: polls the read-back every 100 ms (was a fixed 700 ms) and re-sends once per second if a starting video undid it: 0.7-1.0 s -> 0.03-0.5 s. Fixed a case where pause right after play did not stick.
  - `BROWSER_PREWARM=true` (default): main window opens on youtube.com at startup. First command after start: 13.3 s -> 4.9 s.
  - STT: `language="en"` on the dashboard path too (no detection pass), model loaded in the background at startup (`SpeechToText.warm`, also the wake model): first voice command no longer pays ~3 s; 2.2-2.5 s -> 1.0-2.0 s per short command.
  - `fix_transcript`: observed mishearings "Paws"->pause, "Carro"->karo, "Skip Add"->skip ad.
- Measured, not changed: local routing ~5 ms; Gemini planner 2.3-7.5 s per plan (network/server bound; `reasoning_effort` low/none gave no consistent gain); skip_ad on a real ad ~9 s (YouTube's 5 s countdown before Skip shows).
- End to end via API after restart: play 4.9 s (first) / 4.2 s, pause 0.1-1.4 s, play 0.5 s, voice "video pause karo" 1.7 s, voice "skip ad" 1.5 s, tell_time 0.1 s. All succeeded.
- Tests: 287 passed, 0 failed.

## Blocked on user
- [ ] For the claude.ai website target: stop JARVIS, run `login.ps1`, sign in to claude.ai in the side window
- [ ] Planner LLM: add Anthropic credits, or switch `.env` to a free OpenAI-compatible API (Gemini / Groq) via `LLM_BASE_URL`
- [ ] Check claude.ai stays logged in (user asked to skip LeetCode, so the workspace test was not re-run)
- [ ] Fill `vendor\UFO\config\ufo\agents.yaml` (OpenAI/Azure key) or set `UFO_ENABLED=false` in `.env`
- [ ] Notion values in `.env` if Notion is wanted

## Next action
- Run one UFO Notepad task once agents.yaml is filled; send one new command to exercise the real planner; check claude.ai login persistence.
