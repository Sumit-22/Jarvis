# JARVIS Build Spec for Claude Code

## How to use this doc

Ye doc Claude Code ke liye executable spec hai: Claude Code isko padh ke milestone-by-milestone JARVIS khud build karega, aur sirf secrets, logins ya risky actions pe tumse poochega. Section 1 se aage ka text agent ke liye English mein hai, kyunki instructions jitni precise hongi utna kam galti hogi.

1. Is doc ko Markdown mein export karo aur `C:\Jarvis\JARVIS_SPEC.md` naam se save karo. Folder na ho to bana lo.
2. Usi folder mein ek `CLAUDE.md` file banao jisme bas ek line ho: `Follow JARVIS_SPEC.md. Read PROGRESS.md first if it exists.` Isse har nayi Claude Code session spec aur progress apne aap pakad legi.
3. Windows Terminal (PowerShell, non-admin) kholo, `cd C:\Jarvis` karo, aur Claude Code start karo.
4. Pehla message ye do: `Read JARVIS_SPEC.md fully, then execute it starting from Milestone 0. Keep going milestone by milestone until you hit a STOP condition.`
5. Jab woh rukega to teen hi wajah hongi: koi secret chahiye (API key, Notion token), browser mein manual login chahiye, ya koi consequential action approve karna hai. Kaam karo, phir bolo `continue`.
6. Session lamba ho jaaye ya context bhar jaaye, to nayi session kholo aur bolo `Read PROGRESS.md and continue from the next unfinished milestone.`

Realistic expectation: poora build ek baithak mein nahi hoga. M0 se M3 pehle din mein ho sakte hain; voice, Notion aur UFO baad ki sessions mein aayenge. API keys kabhi chat mein paste mat karna, seedha `.env` file mein daalna.

## 1. Mission and operating rules (for the agent)

Build JARVIS: a local, cost-conscious Windows assistant that turns natural-language commands into verified, repeatable workflows, and reuses saved workflows without calling an LLM.

**Autonomy model**

- Work milestone by milestone, in order. Within a milestone, act without asking.
- When a milestone's acceptance checks all pass, update `PROGRESS.md` and continue to the next milestone automatically.
- Stop only on a STOP condition (below). Never stop just to ask "should I continue?".

**STOP conditions (ask the user, then wait)**

- A secret is needed (LLM API key, Notion token). Ask the user to put it in `.env`; never ask them to paste it in chat.
- A manual browser login is needed (YouTube, LeetCode, Claude).
- An action would delete or overwrite user files outside `C:\Jarvis`, need admin rights, change system settings, install software outside pip/npm, send a message, submit a form, or create real content in an external service.
- An acceptance check still fails after 3 genuine fix attempts. Report what failed, what you tried, and your best hypothesis.
- A real user decision is needed that this spec does not answer.

**Honesty rules**

- Never mark anything working unless you ran it. Label everything else `UNTESTED`.
- Never fake a success state in the UI, logs or `PROGRESS.md`.
- Verify commands against the installed package versions and official docs. Do not copy commands from memory or from earlier AI output without checking.

**Scope discipline**

- Build the smallest version that passes each milestone's checks. No extra features until the MVP (M0 to M5) works.
- Prefer deterministic code over LLM calls everywhere it is practical.

## 2. Target machine and architecture decisions

The target is a CPU-only laptop (Acer Aspire 3, 11th-gen Intel i5, no dedicated GPU, RAM unknown). Measure RAM and free disk in M0 and adjust model sizes to them.

| Area | Decision | Why |
|---|---|---|
| Backend | Python 3.11 or 3.12, FastAPI, Pydantic v2, one venv in `C:\Jarvis\backend\.venv` | Use the newest Python that all pinned deps support; verify in M0 |
| Frontend | Vite + React + TypeScript + Tailwind + Framer Motion | No SSR needed; built output is served by FastAPI, so only one process runs in normal use |
| Browser automation | Playwright (Python), persistent Chromium contexts with dedicated profiles under `C:\Jarvis\data\profiles\` | Deterministic, keeps manual logins, no cookie extraction |
| Window control | `pywin32` (`EnumWindows`, `MoveWindow`, `SetForegroundWindow`) plus `pywinauto` where needed | Deterministic and free; no LLM per step |
| Microsoft UFO | UFO² cloned and installed in M0–M1 in its own venv, wrapped by `DesktopAgentAdapter`; used only for desktop tasks no deterministic tool covers, always with approval | UFO² calls an LLM per step, so pywin32 handles known tasks for free and UFO covers the long tail of new desktop tasks |
| Workflow memory | SQLite via the standard `sqlite3` module or SQLModel | Single file, no server |
| Local intent match | `rapidfuzz` for aliases; optional small CPU embedding model only if fuzzy match proves insufficient | Keeps cache hits free and fast |
| Planner LLM | Provider abstraction; default is an API model configured in `.env` | A 3–4B local model on this CPU is unreliable for structured JSON plans |
| Speech to text | `faster-whisper`, model `base` (or `small`), `compute_type=int8`, CPU | Larger models are too slow for push-to-talk on this CPU |
| Text to speech | `pyttsx3` (Windows SAPI), offline | Zero cost, no extra service |
| Logs | JSON lines to `C:\Jarvis\data\logs\`, every entry has `execution_id` | Traceable runs and verification results |

Components and data flow:

1. UI (browser, localhost) sends a text or voice command to FastAPI over HTTP; progress streams back over a WebSocket.
2. FastAPI passes the text to the Router.
3. Router Stage A (local) tries saved workflows, aliases and slot patterns; on a confident match it returns a stored plan with zero LLM calls.
4. Router Stage B (LLM) runs only on a miss and returns a JSON plan that must validate against the tool registry.
5. The Executor runs each step through the Tool Registry with timeouts, bounded retries and a verification check per step.
6. Tools call Playwright, pywin32, or the Notion API. Results and usage counters go to SQLite and the logs.
7. A verified LLM plan can be saved as a workflow only after the user agrees.

The LLM planner sits off the main path: a saved workflow goes straight from the local router to the executor.

## 3. Project structure and tool registry

Create this layout under `C:\Jarvis`. Adjust file names if needed, but keep the module boundaries.

```
C:\Jarvis
  JARVIS_SPEC.md, CLAUDE.md, PROGRESS.md, README.md
  .env.example, .gitignore
  install.ps1, start.ps1, stop.ps1
  backend\
    pyproject.toml (or requirements.txt + requirements-dev.txt)
    jarvis\
      main.py            FastAPI app, binds 127.0.0.1 only
      config.py          pydantic-settings, reads .env
      api\               REST + WebSocket routes
      router\            normalize.py, local_match.py, slots.py, llm_planner.py
      registry\          workflows (SQLite repo), schema.sql, seed_workflows.py
      executor\          runner.py, verification.py, approvals.py, cancel.py
      tools\             base.py (Tool protocol), browser.py, windows.py, youtube.py,
                         leetcode.py, claude_web.py, notion.py, system.py
      llm\               provider.py (interface), anthropic.py / openai.py, usage.py
      voice\             stt.py (faster-whisper), tts.py (pyttsx3)
      adapters\          ufo_adapter.py (M7, optional)
      logging.py
    tests\
  frontend\              Vite + React app
  data\                  gitignored: jarvis.db, logs\, profiles\
```

Every tool implements one interface: a name, a Pydantic input model, `requires_approval: bool`, a timeout, `run(args) -> ToolResult`, and `verify(args, result) -> VerificationResult`. The executor refuses any tool name not in the registry and any args that fail validation.

| Tool | Input | Backend | Verification | Approval |
|---|---|---|---|---|
| `open_url` | `url`, `window` (`main` or `side`) | Playwright | page URL matches expected host | No |
| `search_youtube` | `query` | Playwright | results page has video links | No |
| `play_youtube_result` | `index` (default 0) | Playwright | URL is `/watch`, video element exists; report if paused by autoplay policy | No |
| `open_leetcode_problem` | `slug` or `url` | Playwright | URL contains `/problems/<slug>`; report login or Cloudflare wall | No |
| `open_claude` | none | Playwright, separate context | page loaded; report if login needed | No |
| `get_problem_summary` | `slug` | LeetCode page text, then LLM API | non-empty summary | Yes, sends problem text to the LLM provider |
| `arrange_windows` | `left_title`, `right_title`, `layout` (`side_by_side`) | pywin32 | both HWNDs exist, rects match target halves of the monitor work area | No |
| `get_active_window` | none | pywin32 | returns title and HWND | No |
| `verify_workspace` | `expected_windows` | pywin32 + Playwright | all expected windows present and laid out | No |
| `ufo_desktop_task` | `task` (plain-language desktop request), `timeout_s` | UFO² via `DesktopAgentAdapter` | UFO exit status plus its run log; any failure or timeout is reported as failed | Yes, every run |
| `create_notion_page` | `title`, `content_blocks`, `parent_id` | Notion API | response has page `id` and `url` | Yes |
| `create_notion_db_entry` | `database_id`, `properties` | Notion API | response has page `id` | Yes |
| `speak` | `text` | pyttsx3 | no exception | No |

No tool may run arbitrary shell commands. There is no `run_shell` tool.

## 4. Router, workflow memory and slot filling

A command that matches a saved workflow must execute with zero LLM calls; this is the core cost requirement and must be proven by a test.

**SQLite schema (minimum)**

- `workflows`: `id`, `name` (unique), `canonical_intent`, `version`, `params_schema` (JSON Schema), `steps` (JSON list of `{tool, args_template, verify}`), `created_at`, `last_used_at`, `enabled`.
- `workflow_aliases`: `workflow_id`, `alias` (normalized text).
- `workflow_patterns`: `workflow_id`, `regex` with named groups that map to params (for example `^(play|search)( a)? (video|videos)? (about|on) (?P<query>.+)$`).
- `executions`: `id`, `workflow_id` (nullable), `command_text`, `route` (`local` or `llm`), `status` (`succeeded`, `failed`, `cancelled`, `needs_input`), `started_at`, `ended_at`, `error`.
- `execution_steps`: per-step tool, validated args, attempts, result, verification result.
- `llm_usage`: `execution_id`, `purpose` (`planner`, `summary`, `stt`, other), `provider`, `model`, `input_tokens`, `output_tokens`, `est_cost`.

Never store secrets, cookies or passwords in this database.

**Stage A: local routing, in this order**

1. Normalize: lowercase, trim, strip punctuation and filler words (`please`, `jarvis`, `can you`).
2. History intents, handled by fixed rules: "repeat the last workflow", "repeat what we did yesterday" query `executions` (latest succeeded run, or latest on that date) and re-run its workflow with the same params. If several match, ask which one.
3. Pattern match: try `workflow_patterns`; named groups fill params.
4. Alias match: exact alias first, then `rapidfuzz` `token_set_ratio`. Score ≥ 90 is a hit. Score 75–89 asks the user to confirm. Below 75 is a miss.
5. Validate filled params against `params_schema`. A required param that is missing gets a question to the user, not an LLM call.

**Stage B: LLM planner, only on a miss**

- Send only: the current command, the tool registry (names, descriptions, input schemas), and the names of saved workflows. Never the full conversation.
- Require a JSON plan; validate it with Pydantic against the registry. Invalid plan gets one repair attempt, then fail with a clear error.
- Record usage in `llm_usage` with `purpose=planner`.

**Saving a workflow**

- Only after an LLM plan executes and every step verifies, offer: "Save this as a workflow? Suggested name: X."
- On yes, store steps with concrete values turned into params where obvious, plus the command text as the first alias. Never auto-save.
- Editing a saved workflow bumps `version`; keep the old version row.

**Seed workflows (created in M3, used to test routing)**

- `youtube_play(query)`: `search_youtube` then `play_youtube_result`.
- `coding_workspace(slug?)`: `open_leetcode_problem`, `open_claude`, `arrange_windows`, `verify_workspace`. If `slug` is missing, ask which problem.
- `notion_meeting_notes(title, notes)`: `create_notion_page`. Never invent notes; ask if missing.

**Usage reporting**

The UI and `GET /api/usage` show: planner calls, cache hits, cache misses, input/output tokens, and estimated cost, split by `purpose`. Never show "zero cost" for a run if any component used a paid API.

## 5. Milestones, acceptance checks and stop points

The MVP is M0 to M5; M6 and M7 are add-ons. A milestone is done only when every acceptance check passes and is recorded in `PROGRESS.md`.

**M0: Inspect the machine (read-only)**

- Report: Windows edition and build, CPU, RAM, free disk on `C:`, installed Python versions (`py -0p`), Git, Node.js and npm versions, PowerShell version and execution policy.
- Check whether `C:\Jarvis` already has content; if yes, list it and back up any existing config to `C:\Jarvis\_backup_<timestamp>\` before changing anything.
- Look for an existing Microsoft UFO clone at `C:\Jarvis\vendor\UFO`. If missing, clone `https://github.com/microsoft/UFO` there (clone only, no install yet). Read its README and docs and record: commit hash, the UFO² launch command, the config template it needs, and its supported Python version. Use UFO² (the stable Windows agent), not Galaxy.
- Missing prerequisite (Python 3.11+, Node 20+, Git, or the Python version UFO requires): STOP and tell the user exactly what to install from which official site. Do not install system software yourself.
- Acceptance: an "Environment" section in `PROGRESS.md` with every value above and a go/no-go per prerequisite, plus a "UFO" section with commit, Python requirement, launch command and config files, each taken from the repo's own docs.

**M1: Skeleton and install scripts**

- Create the layout from Section 3, `.gitignore`, `.env.example` (placeholders only), `git init`.
- `install.ps1`: checks prerequisites, creates the JARVIS venv, installs Python deps, runs `playwright install chromium`, runs `npm ci` or `npm install` in `frontend`. Idempotent, no admin, clear error messages.
- UFO setup inside `install.ps1`: a separate venv at `C:\Jarvis\vendor\UFO\.venv` using the Python version UFO's docs require, then its own requirements. JARVIS and UFO never share a venv. Copy UFO's config template to its real config file exactly as its docs say.
- STOP: ask the user to fill the API key and model in UFO's config file themselves. Never read the key back, print it, or copy it elsewhere.
- `start.ps1` starts the backend on `127.0.0.1:8765` (dev: also the Vite dev server); `stop.ps1` stops them by saved PIDs.
- Acceptance: `install.ps1` runs twice without errors; `start.ps1` brings up `GET /api/health` returning 200; `stop.ps1` stops it; UFO² completes one harmless task through its documented CLI (for example opening Notepad), and the result is recorded in `PROGRESS.md`.

**M2: Registry, router, executor (no real tools yet)**

- SQLite schema, migrations on startup, tool interface, executor with timeout, bounded retries (max 2), cancellation, approval gate, dry-run mode, JSON logs.
- Router Stage A and Stage B with a mock LLM provider; seed workflows from Section 4.
- Acceptance (pytest, all external calls mocked):
  - local alias hit, fuzzy hit, confirm band, miss
  - pattern slot extraction for `youtube_play`
  - **a saved-workflow command makes zero planner calls** (assert the mock provider was never called)
  - a miss calls the planner exactly once and records usage
  - invalid plan and invalid params are rejected
  - retry limit is respected; timeout gives `failed`
  - a tool with `requires_approval` does not run without approval
  - "repeat the last workflow" reads `executions`

**M3: Browser and window tools**

- Implement `open_url`, `search_youtube`, `play_youtube_result`, `open_leetcode_problem`, `open_claude`, `arrange_windows`, `get_active_window`, `verify_workspace`.
- One long-lived Playwright instance owned by the backend. Two persistent contexts with separate profiles (`main`, `side`) so they are two real OS windows. Never open a new browser per command.
- Find each window's HWND by title, move it with `MoveWindow` to the left and right halves of the monitor work area, then read the rects back to verify.
- Implement `DesktopAgentAdapter` and the `ufo_desktop_task` tool: run UFO²'s documented CLI as a subprocess with the UFO venv's Python, with timeout and cancellation, and parse its exit status and log. Known tasks (windows, layout, verification) always use the pywin32 tools, never UFO.
- Unit tests for argument validation with Playwright, pywin32 and the UFO subprocess mocked.
- STOP once: ask the user to log in manually in the `main` and `side` windows (YouTube or Google, LeetCode, claude.ai) if they want logged-in sessions.
- Acceptance (manual smoke run, recorded in `PROGRESS.md`): `youtube_play("python decorators")` reaches a `/watch` page; `coding_workspace("two-sum")` shows LeetCode left and Claude right, and `verify_workspace` passes. Run it a second time and confirm the route was `local` with zero planner calls and zero UFO calls.

**M4: Dashboard**

- Dark theme, cyan accents, animated orb that reflects real backend state (idle, listening, planning, executing, error).
- Text command box, conversation list, live step timeline over WebSocket, current task and step, saved-workflow list with run buttons, tool activity panel, usage panel, Stop button, approval dialog, error with Retry.
- All status comes from backend events; the UI never infers success.
- Production build served by FastAPI at `http://127.0.0.1:8765`.
- Acceptance: running `coding_workspace` from the UI shows each step live; Stop cancels a running step within 2 seconds; an approval-gated tool shows the dialog and does nothing until approved.

**M5: Notion and real planner**

- STOP: ask the user to add `LLM_API_KEY`, `LLM_PROVIDER`, `LLM_MODEL`, `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID` to `.env` and to share the parent page with their Notion integration.
- Notion client: validate the parent at startup, build page payloads from user text only, handle 429 with backoff, return page URL and ID.
- Real LLM provider behind the same interface; usage recorded from the provider's response.
- Unit tests: Notion payload construction, 4xx and 429 handling, planner JSON validation, all mocked.
- Acceptance: one real Notion page created only after the user approves it in the UI; one new command routed through the real planner, saved as a workflow on user consent, then re-run locally with zero planner calls.

**M6: Voice and TTS (add-on)**

- Push-to-talk in the UI; audio sent to the backend; `faster-whisper` with model from `.env` (default `base`, `int8`).
- Show transcript, then route as text. TTS speaks a one-line result when enabled.
- Text input keeps working if the mic or STT fails.
- Acceptance: a spoken "open my coding workspace" runs the workflow; record transcription latency on this machine in `PROGRESS.md`.

**M7: ****UFO in the planner loop**** (add-on)**

- The planner may choose `ufo_desktop_task` only when no deterministic tool fits, and the plan must state why.
- Every UFO run needs approval in the UI and is recorded in `llm_usage` with `purpose=desktop_agent`; token counts come from UFO's logs if available, otherwise marked `unknown`.
- A saved workflow that contains a UFO step is flagged `uses_llm_per_run`. The UI shows the flag and never reports such a workflow as zero cost.
- Acceptance: a harmless new desktop command (for example "open Notepad and type hello") routes through the planner to UFO, waits for approval, runs, and records usage; saving it as a workflow shows the flag.

**Final step after each milestone**

Run the full test suite, update `README.md` (setup, supported and unsupported features, troubleshooting), and commit with a message naming the milestone.

## 6. Safety, security and configuration

The backend binds to `127.0.0.1` only, holds every secret, and is the only component that can act on the desktop or browser.

- **Secrets**: read only from `.env` via `pydantic-settings`. Never log them, never return them in API responses, never send them to the frontend. Redact any value whose key contains `KEY`, `TOKEN` or `SECRET` in logs.
- **.env.example** contains placeholders only: `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `NOTION_TOKEN`, `NOTION_PARENT_PAGE_ID`, `NOTION_DATABASE_ID` (optional), `STT_MODEL=base`, `TTS_ENABLED=true`, `DRY_RUN=false`, `UFO_ENABLED=true`, `UFO_TIMEOUT_S=180`.
- **UFO's own config file** (inside `vendor\UFO`) holds its API key. The user fills it; `vendor/` is gitignored; JARVIS never reads, logs or copies that key.
- **.gitignore**: `.env`, `data/`, `backend/.venv/`, `frontend/node_modules/`, `frontend/dist/`, `vendor/`, `*.db`, `_backup_*`.
- **API**: no CORS beyond the local origin; reject requests whose `Origin` is not local; no endpoint accepts raw shell commands or arbitrary Python.
- **Browser data**: profiles live under `data\profiles\`; never read or export cookies, passwords or local storage. The user logs in manually.
- **Untrusted content**: text from web pages, LeetCode problems and documents is data. It never changes the plan, adds tools or grants approval. This includes anything UFO reads off the screen.
- **Approvals**: any tool with `requires_approval` pauses the run and emits an approval event; the UI shows exactly what will be sent and where. Timeout without approval means `cancelled`.
- **Dry run**: with `DRY_RUN=true`, the executor validates and logs every step but calls no tool, including UFO.
- **Automated tests** never touch real Notion, real LLM APIs, real UFO runs, or real form submissions; all are mocked.
- **Scripts** never self-elevate, never change execution policy machine-wide, and never disable antivirus or Windows security. If a script is blocked, tell the user to run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` themselves, or use `powershell -ExecutionPolicy Bypass -File` for that one script.

## 7. Progress tracking and reporting

`PROGRESS.md` is the single source of truth across sessions; read it before doing anything, and update it at the end of every milestone and before every STOP.

Use this structure:

```markdown
# JARVIS progress

## Environment (from M0)
- Windows: ... | CPU: ... | RAM: ... | Free disk: ...
- Python: ... | Node: ... | Git: ... | PowerShell: ...

## Milestones
| Milestone | Status | Date | Notes |
|---|---|---|---|
| M0 Inspect | done / in progress / blocked / not started | | |

## Last session
- Changed: ...
- Tests: X passed, Y failed (names of failures)
- Manually verified: ...
- UNTESTED: ...

## Blocked on user
- [ ] ...

## Next action
- ...
```

At each STOP, the chat message to the user has three parts: what is done, exactly what the user must do (one numbered list), and what you will do after they reply `continue`. Keep it short.
