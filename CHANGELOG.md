# Changelog

Measured numbers are from the target laptop (i5-1135G7, 8 GB RAM, Windows 11) against real YouTube.
Session-by-session test notes stay in `PROGRESS.md`.

## 2026-10-24 — YouTube skip ad, play fix, performance pass, free LLM

### Added
- **Skip ad** (`skip_ad` tool + workflow): "skip ad", "skip the ad", "skip ads", "ad skip karo", "ad skip kar do",
  "ad hatao". Clicks YouTube's Skip button in JARVIS's own browser window (waits up to 8 s for it to appear),
  then reads back whether the ad is gone. Says "No ad is playing." when there is none; an unskippable ad fails
  with that reason. Plain "skip" still means next track.
- **More Hinglish pause/play**: "video pause karo", "youtube play karo", "pause kar do", "play karo",
  "wapas chalao", "phir se chalao", "pause the youtube video".
- **Free planner LLM**: `LLM_BASE_URL` lets `LLM_PROVIDER=openai` use any OpenAI-compatible server
  (Gemini free tier, Groq, local Ollama — no key needed for localhost). Now running on `gemini-3.5-flash`.
- **`BROWSER_PREWARM`** (default `true`): JARVIS's browser window opens on youtube.com at startup.
- **Voice transcript fixes** for observed mishearings: "Paws" → pause, "Carro" → karo, "Skip Add" → skip ad.

### Fixed
- **"No such result on the page" after a fresh start**: YouTube sometimes re-renders the results list after the
  search step has read it, so the play step found no links. The search step now remembers the video links and
  the play step uses them; only the visible results page is read (YouTube keeps old pages hidden in the DOM).
- **Pause right after a video starts did not stick**: the starting player undid it. Pause/play now re-sends
  once a second until the read-back matches.
- **Chromium "Executable doesn't exist"** when JARVIS was started from a terminal opened before the user env
  vars were set: `start.ps1` now passes `PLAYWRIGHT_BROWSERS_PATH` and `HF_HOME` to the backend itself.
- **Dashboard mic button sent nothing**: hold-to-talk raced the microphone permission prompt. Now click to
  start, click again to send.

### Performance

| Action | Before | After | How |
|---|---|---|---|
| First YouTube command after start | 13.3 s | 4.9 s | browser prewarm |
| YouTube play (search + open) | 8.8–12.6 s | 2.7–4.4 s | below |
| ↳ search step | 3.0–4.3 s | 1.7–2.9 s | types into YouTube's own search box when YouTube is open (no page load) |
| ↳ open video step | 5.8–8.7 s | 1.0–3.3 s | clicks inside the loaded page; polls until the video moves instead of a fixed 2.5 s sleep |
| Pause / play | 0.7–1.0 s | 0.03–0.5 s | polls the read-back every 100 ms instead of a fixed 700 ms |
| Voice command → text | 2.2–2.5 s (first: 5.9 s) | 1.0–2.0 s | language fixed to English (no detection pass); model loaded at startup |

Measured and left as is:
- Local command matching: ~5 ms.
- Gemini planner: 2.3–7.5 s per plan, spent on Google's side; lower reasoning effort gave no consistent gain.
  Known commands (YouTube, pause, skip ad, volume…) never call the planner.
- Skip ad on a real ad: ~9 s, because YouTube shows the Skip button only after its ~5 s countdown.

### Not yet tested
- Voice commands with the user's own voice through the dashboard mic (tested with generated speech files).

## 2026-10-21 – 2026-10-22 — everyday commands, dashboard, Claude bridge, voice

- **Everyday tools** (`tools/daily.py`): web search, sites, apps (incl. any Start-menu app), time, media keys,
  volume with read-back, timers, screenshots, scroll, Nth visible video, fullscreen, screen rotation
  (approval required). English + Hinglish patterns, all routed locally.
- **Dashboard redesign**: glass panels, orb, quick actions, step timeline, timer toasts, mobile layout.
- **Claude bridge** (`tools/claude_bridge.py`): "ask claude to …" runs Claude Code in the background with
  approval first, streams progress, speaks the answer.
- **Voice**: Indian voices (Swara, Neerja, Heera, Zira) chosen in the dashboard; "Hello Archu" wake word
  (`voice/wake.py`), pauses JARVIS's video and lowers volume while listening.
- Fixes: TTS hang after many runs, browser relaunch when the user closes a window, Claude stream reader dying
  on lines over 64 KB.
