import { AnimatePresence, LayoutGroup, animate, motion, useReducedMotion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api, connectEvents, type JarvisEvent, type OrbState, type PrefsView, type UpdateInfo, type Usage, type Workflow } from "./api";
import { Icon, workflowIcon } from "./Icon";
import { Orb, PALETTE } from "./Orb";

type Msg = { id: number; role: "user" | "jarvis"; text: string; tone?: "answer" | "error" | "info"; action?: RouteAction };
type RouteAction = {
  kind: "needs_input" | "confirm" | "choose" | "offer_save" | "retry";
  workflow?: string | null;
  params?: Record<string, unknown>;
  missing?: string[];
  options?: { workflow: string; params: Record<string, unknown>; command: string }[];
  execution_id?: string;
  suggested_name?: string;
  command?: string;
  done?: boolean;
};
type Step = { idx: number; tool: string; status: string; attempts?: number; detail?: string; args?: unknown };
type Run = { execution_id: string; steps: Step[]; status: string; error?: string | null; route?: string; workflow?: string | null; started: number };
type Approval = { approval_id: string; tool: string; description: string; execution_id: string };
type Toast = { id: number; title: string; body: string; icon?: string };
type ClaudeJob = {
  target: "code" | "web"; prompt: string; status: "running" | "done" | "failed" | "stopped"; session_id?: string | null;
  url?: string | null; cwd?: string | null; mode?: string | null; model?: string | null; steps: string[]; files: string[];
  plan?: string | null; result: string; error?: string | null; cost_usd?: number | null; elapsed_s: number;
  answer?: string;
};

type UpdateState = { info?: UpdateInfo; checking: boolean; checkError?: string; phase: "idle" | "applying" | "done" | "failed"; log: string[]; error?: string };
// Set by the desktop app (pywebview); absent in a normal browser.
type DesktopApi = { restart: () => Promise<boolean> };
const desktopApi = () => (window as unknown as { pywebview?: { api?: DesktopApi } }).pywebview?.api;

const SPRING = { type: "spring", stiffness: 380, damping: 32 } as const;

const QUICK = [
  { label: "Time", cmd: "what time is it", icon: "clock" },
  { label: "Weather", cmd: "what's the weather", icon: "cloud" },
  { label: "Gmail", cmd: "open gmail", icon: "mail" },
  { label: "Lofi", cmd: "play lofi beats on youtube", icon: "play" },
  { label: "Play / Pause", cmd: "pause", icon: "pause" },
  { label: "Volume +", cmd: "volume up", icon: "volume" },
  { label: "Screenshot", cmd: "take a screenshot", icon: "camera" },
  { label: "Timer 5m", cmd: "set a timer for 5 minutes", icon: "timer" },
  { label: "Notepad", cmd: "open notepad", icon: "note" },
];
const SUGGESTIONS = ["google best laptops under 50000", "directions to india gate", "remind me in 20 minutes to drink water", "youtube pe arijit singh chalao", "open my downloads", "repeat the last workflow"];

function useMedia(query: string) {
  const [match, setMatch] = useState(() => typeof window !== "undefined" && window.matchMedia(query).matches);
  useEffect(() => {
    const m = window.matchMedia(query);
    const on = () => setMatch(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, [query]);
  return match;
}

let msgId = 0;
let toastId = 0;

export default function App() {
  const [connected, setConnected] = useState(false);
  const [orb, setOrb] = useState<OrbState>("idle");
  const [messages, setMessages] = useState<Msg[]>([]);
  const [run, setRun] = useState<Run | null>(null);
  const [activity, setActivity] = useState<{ t: string; text: string; ok?: boolean }[]>([]);
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [health, setHealth] = useState<{ dry_run: boolean; llm_provider: string; llm_model: string } | null>(null);
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [claude, setClaude] = useState<ClaudeJob | null>(null);
  const [voice, setVoice] = useState<PrefsView | null>(null);
  const [input, setInput] = useState("");
  const [update, setUpdate] = useState<UpdateState>({ checking: false, phase: "idle", log: [] });
  const checkUpdate = useCallback(async () => {
    setUpdate((u) => ({ ...u, checking: true, checkError: undefined }));
    try {
      const info = await api.updateCheck();
      setUpdate((u) => ({ ...u, info, checking: false }));
    } catch (err) {
      setUpdate((u) => ({ ...u, checking: false, checkError: (err as Error).message }));
    }
  }, []);
  const applyUpdate = useCallback(async () => {
    setUpdate((u) => ({ ...u, phase: "applying", log: [], error: undefined }));
    try { await api.updateApply(); } catch (err) { setUpdate((u) => ({ ...u, phase: "failed", error: (err as Error).message })); }
  }, []);
  const lastCommand = useRef("");
  const inputRef = useRef<HTMLInputElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  const say = useCallback((role: Msg["role"], text: string, action?: RouteAction, tone?: Msg["tone"]) => {
    setMessages((m) => [...m.slice(-80), { id: ++msgId, role, text, action, tone }]);
  }, []);
  const toast = useCallback((title: string, body: string, icon?: string) => {
    const id = ++toastId;
    setToasts((t) => [...t, { id, title, body, icon }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 8000);
  }, []);
  const refresh = useCallback(() => {
    api.workflows().then(setWorkflows).catch(() => {});
    api.usage().then(setUsage).catch(() => {});
  }, []);

  const onEvent = useCallback(
    (e: JarvisEvent) => {
      const now = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      switch (e.type) {
        case "hello":
          setOrb(e.state);
          setApprovals(e.pending_approvals ?? []);
          break;
        case "state":
          setOrb(e.state);
          break;
        case "route":
          if (e.kind === "run") {
            const how = e.route === "local" ? `on-device (${e.via || "direct"}) · 0 planner calls` : "LLM planner";
            say("jarvis", `Running ${pretty(e.workflow) ?? "a new plan"} · ${how}${e.reason ? ` — ${e.reason}` : ""}`, undefined, "info");
            setRun({ execution_id: e.execution_id, steps: e.steps.map((s: any, i: number) => ({ idx: i, tool: s.tool, status: "pending", args: s.args })), status: "running", route: e.route, workflow: e.workflow, started: Date.now() });
          } else if (e.kind === "needs_input") {
            say("jarvis", e.message, e.workflow ? { kind: "needs_input", workflow: e.workflow, params: e.params, missing: e.missing } : undefined);
          } else if (e.kind === "confirm") {
            say("jarvis", e.message, { kind: "confirm", workflow: e.workflow });
          } else if (e.kind === "choose") {
            say("jarvis", e.message, { kind: "choose", options: e.options });
          } else {
            say("jarvis", e.message || "I couldn't route that.", { kind: "retry", command: lastCommand.current }, "error");
          }
          break;
        case "step_started":
          setRun((r) => r && r.execution_id === e.execution_id ? { ...r, steps: r.steps.map((s) => (s.idx === e.step ? { ...s, status: "running" } : s)) } : r);
          setActivity((a) => [...a.slice(-60), { t: now, text: `▶ ${e.tool} ${JSON.stringify(e.args)}` }]);
          break;
        case "step_retry":
          setActivity((a) => [...a.slice(-60), { t: now, text: `↻ ${e.tool} attempt ${e.attempt} failed: ${e.error}`, ok: false }]);
          break;
        case "step_finished":
          setRun((r) => r && r.execution_id === e.execution_id ? { ...r, steps: r.steps.map((s) => s.idx === e.step ? { ...s, status: e.status, attempts: e.attempts, detail: e.verification?.detail ?? e.error ?? "" } : s) } : r);
          setActivity((a) => [...a.slice(-60), { t: now, text: `${e.status === "succeeded" ? "✓" : e.status === "skipped_dry_run" ? "○" : "✗"} ${e.tool}: ${e.status}${e.verification?.detail ? ` — ${e.verification.detail}` : ""}${e.error ? ` — ${e.error}` : ""}`, ok: e.status === "skipped_dry_run" ? undefined : e.status === "succeeded" }]);
          break;
        case "run_finished":
          setRun((r) => (r && r.execution_id === e.execution_id ? { ...r, status: e.status, error: e.error } : r));
          if (e.status === "succeeded") {
            if (e.dry_run) say("jarvis", "Dry run finished: every step validated, nothing was executed.");
            else if (e.say) say("jarvis", e.say, undefined, "answer");
            else say("jarvis", "Done. Every step was verified.");
          } else say("jarvis", `Run ${e.status}: ${e.error ?? ""}`, e.status === "failed" ? { kind: "retry", command: lastCommand.current } : undefined, "error");
          refresh();
          break;
        case "approval_request":
          setApprovals((a) => [...a, { approval_id: e.approval_id, tool: e.tool, description: e.description, execution_id: e.execution_id }]);
          break;
        case "approval_resolved":
        case "approval_timeout":
          setApprovals((a) => a.filter((x) => x.approval_id !== e.approval_id));
          break;
        case "offer_save":
          say("jarvis", e.message, { kind: "offer_save", execution_id: e.execution_id, suggested_name: e.suggested_name });
          break;
        case "workflow_saved":
          say("jarvis", `Saved workflow ${e.workflow.name} (v${e.workflow.version}). Next time it runs on-device${e.workflow.uses_llm_per_run ? ", but it still calls an LLM on every run (UFO step)" : " with zero planner calls"}.`);
          refresh();
          break;
        case "transcript":
          say("user", `🎙 ${e.text}`);
          setActivity((a) => [...a.slice(-60), { t: now, text: `transcribed in ${e.latency_s}s` }]);
          break;
        case "timer_done":
          toast("Timer", e.message);
          say("jarvis", `⏰ ${e.message}`, undefined, "answer");
          break;
        case "claude_update":
          setClaude(e as unknown as ClaudeJob);
          break;
        case "claude_done":
          setClaude(e as unknown as ClaudeJob);
          toast(e.target === "code" ? "Claude Code" : "Claude", e.say, "sparkle");
          say("jarvis", e.say, undefined, e.status === "done" ? "answer" : "error");
          break;
        case "prefs":
          setVoice(e as unknown as PrefsView);
          break;
        case "wake":
          toast("Archu", "Haan ji, boliye…", "mic");
          break;
        case "warning":
          say("jarvis", `⚠ ${e.message}`, undefined, "error");
          break;
        case "update_progress":
          setUpdate((u) => ({ ...u, phase: "applying", log: [...u.log, e.message] }));
          break;
        case "update_done":
          setUpdate((u) => ({ ...u, phase: e.updated ? "done" : "idle", log: [...u.log, e.message] }));
          if (e.updated) toast("Update installed", "Restart JARVIS to finish.", "update");
          break;
        case "update_failed":
          setUpdate((u) => ({ ...u, phase: "failed", error: e.message }));
          break;
      }
    },
    [say, refresh, toast],
  );

  useEffect(() => connectEvents(onEvent, setConnected), [onEvent]);
  useEffect(() => {
    refresh();
    api.health().then(setHealth).catch(() => {});
    api.prefs().then(setVoice).catch(() => {});
  }, [refresh]);
  useEffect(() => {
    const t = window.setTimeout(checkUpdate, 4000);  // quietly look for updates once after start
    return () => window.clearTimeout(t);
  }, [checkUpdate]);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);
  useEffect(() => {
    const onKey = (ev: KeyboardEvent) => {
      if (ev.key === "/" && document.activeElement?.tagName !== "INPUT") { ev.preventDefault(); inputRef.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const send = async (text: string) => {
    if (!text.trim()) return;
    lastCommand.current = text;
    say("user", text);
    setInput("");
    try {
      await api.command(text);
    } catch (err) {
      say("jarvis", `Request failed: ${(err as Error).message}`, { kind: "retry", command: text }, "error");
    }
  };
  const runWf = (name: string, params: Record<string, unknown> = {}) =>
    api.runWorkflow(name, params).catch((err) => say("jarvis", `Request failed: ${err.message}`, undefined, "error"));
  const markDone = (id: number) => setMessages((m) => m.map((x) => (x.id === id && x.action ? { ...x, action: { ...x.action, done: true } } : x)));

  const running = run?.status === "running";
  const busy = orb === "planning" || orb === "executing";
  const shortScreen = useMedia("(max-height: 860px), (max-width: 640px)");

  return (
    <div className="relative min-h-full overflow-x-hidden lg:h-full">
      <Aurora state={connected ? orb : "offline"} />
      <div className="relative z-10 mx-auto flex max-w-[1560px] flex-col gap-4 p-3 sm:p-5 lg:h-full">
        <TopBar connected={connected} health={health} running={running} onStop={() => api.stop(run?.execution_id)} voice={voice} setVoice={setVoice} update={update} checkUpdate={checkUpdate} applyUpdate={applyUpdate} />

        <main className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-[240px_minmax(0,1fr)_280px] xl:grid-cols-[300px_minmax(0,1fr)_340px]">
          {/* Left: orb, quick actions, usage */}
          <aside className="flex min-h-0 flex-col gap-4">
            <motion.section className={`glass flex shrink-0 flex-col items-center px-5 ${shortScreen ? "pb-4 pt-5" : "pb-6 pt-9"}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={SPRING}>
              <Orb state={orb} connected={connected} size={shortScreen ? 96 : 160} />
            </motion.section>
            <Card title="Quick actions" icon="bolt" delay={0.05} className="lg:min-h-[9.5rem] lg:flex-1">
              <div className="no-scrollbar grid max-h-[11.5rem] min-h-0 auto-rows-max grid-cols-3 content-start gap-2 lg:max-h-none lg:flex-1 overflow-y-auto overscroll-contain px-4 pb-4 pt-1 [mask-image:linear-gradient(to_bottom,black_calc(100%-1.25rem),transparent)]">
                {QUICK.map((q) => (
                  <motion.button key={q.label} whileHover={{ y: -2 }} whileTap={{ scale: 0.94 }} transition={SPRING}
                    disabled={!connected || running} onClick={() => send(q.cmd)} title={q.cmd}
                    className="group flex min-h-11 flex-col items-center gap-1.5 rounded-2xl bg-white/[0.04] px-1 py-3 text-[12px] text-slate-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/70 ring-1 ring-white/[0.06] transition hover:bg-white/[0.08] hover:text-white disabled:opacity-40">
                    <span className="grid h-8 w-8 place-items-center rounded-full bg-gradient-to-br from-cyan/25 to-blue/25 text-cyan transition group-hover:from-cyan/40 group-hover:to-blue/40">
                      <Icon name={q.icon} />
                    </span>
                    {q.label}
                  </motion.button>
                ))}
              </div>
            </Card>
            <UsagePanel usage={usage} />
          </aside>

          {/* Middle: conversation + composer */}
          <motion.section className="glass order-first flex min-h-[70vh] min-h-[70dvh] flex-col overflow-hidden lg:order-none lg:min-h-0" initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ ...SPRING, delay: 0.03 }}>
            <div className="flex items-center justify-between px-5 pt-4">
              <div className="eyebrow">Conversation</div>
              {messages.length > 0 && <button className="text-xs text-dim transition hover:text-white" onClick={() => setMessages([])}>Clear</button>}
            </div>
            <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-4 sm:px-6">
              {messages.length === 0 && <EmptyState onPick={send} disabled={!connected} />}
              <LayoutGroup>
                <AnimatePresence initial={false}>
                  {messages.map((m) => (
                    <motion.div key={m.id} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0 }} transition={SPRING}
                      className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
                      <Bubble m={m}>
                        {m.action && !m.action.done && <ActionBar action={m.action} onDone={() => markDone(m.id)} runWf={runWf} send={send} say={say} />}
                      </Bubble>
                    </motion.div>
                  ))}
                  {busy && (
                    <motion.div key="typing" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, scale: 0.9 }} transition={SPRING}>
                      <TypingDots color={PALETTE[orb][0]} />
                    </motion.div>
                  )}
                </AnimatePresence>
              </LayoutGroup>
            </div>
            <Composer inputRef={inputRef} value={input} setValue={setInput} connected={connected} onSend={() => send(input)} onError={(m) => say("jarvis", m, undefined, "error")} />
          </motion.section>

          {/* Right: current task, workflows, activity */}
          <aside className="flex min-h-0 flex-col gap-4 lg:-mr-1 lg:overflow-y-auto lg:pr-1 [&>*]:shrink-0">
            <AnimatePresence>{claude && <ClaudeCard job={claude} connected={connected} send={send} />}</AnimatePresence>
            <TaskCard run={run} />
            <WorkflowsCard workflows={workflows} disabled={running || !connected} runWf={runWf} />
            <Card title="Tool activity" icon="list" className="max-h-56 lg:max-h-none lg:min-h-48 lg:flex-1" delay={0.12}>
              <ul className="space-y-1 overflow-y-auto px-4 pb-4 font-mono text-[11px] leading-relaxed">
                {activity.length === 0 && <li className="text-dim">No tool calls yet.</li>}
                {activity.slice().reverse().map((a, i) => (
                  <li key={activity.length - i} className={a.ok === false ? "text-rose" : a.ok ? "text-mint" : "text-dim"}><span className="text-slate-600">{a.t}</span> {a.text}</li>
                ))}
              </ul>
            </Card>
          </aside>
        </main>
      </div>

      <ApprovalDialog approval={approvals[0]} />
      <Toasts toasts={toasts} dismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </div>
  );
}

const pretty = (name?: string | null) => (name ? name.replace(/_/g, " ") : name);

/* ---------- layout pieces ---------- */

function Aurora({ state }: { state: OrbState | "offline" }) {
  const [a, b, c] = PALETTE[state];
  const blobs = [
    { col: a, cls: "-left-40 -top-40 h-[34rem] w-[34rem]" },
    { col: b, cls: "-right-48 top-1/4 h-[38rem] w-[38rem]" },
    { col: c, cls: "-bottom-56 left-1/3 h-[36rem] w-[36rem]" },
  ];
  return (
    <div className="pointer-events-none fixed inset-0 overflow-hidden" aria-hidden>
      {blobs.map((bl, i) => (
        <motion.div key={i} className={`absolute rounded-full blur-[120px] ${bl.cls}`}
          animate={{ backgroundColor: bl.col }}
          style={{ opacity: 0.24 }}
          transition={{ backgroundColor: { duration: 1.2 } }} />
      ))}
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_center,transparent_0%,#03050a_85%)]" />
      <div className="absolute inset-0 opacity-[0.035] [background-image:linear-gradient(rgba(255,255,255,.6)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.6)_1px,transparent_1px)] [background-size:48px_48px]" />
    </div>
  );
}

function TopBar({ connected, health, running, onStop, voice, setVoice, update, checkUpdate, applyUpdate }: {
  connected: boolean; health: { dry_run: boolean; llm_provider: string; llm_model: string } | null; running: boolean; onStop: () => void;
  voice: PrefsView | null; setVoice: (v: PrefsView) => void;
  update: UpdateState; checkUpdate: () => void; applyUpdate: () => void;
}) {
  const [updOpen, setUpdOpen] = useState(false);
  const available = (update.info?.behind ?? 0) > 0 || update.phase === "done";
  const [clock, setClock] = useState(() => new Date());
  const [panel, setPanel] = useState(false);
  const wakeOn = !!voice?.wake.running;
  useEffect(() => { const t = window.setInterval(() => setClock(new Date()), 15000); return () => window.clearInterval(t); }, []);
  return (
    <motion.header className="glass relative flex items-center justify-between gap-3 px-4 py-2.5 sm:px-5" initial={{ opacity: 0, y: -10 }} animate={{ opacity: 1, y: 0 }} transition={SPRING}>
      <div className="flex min-w-0 items-center gap-3">
        <div className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-cyan to-blue text-black shadow-[0_0_24px_-4px] shadow-cyan/60">
          <Icon name="sparkle" className="h-4 w-4" strokeWidth={2.2} />
        </div>
        <div className="min-w-0 leading-tight">
          <div className="text-[15px] font-semibold tracking-tight">JARVIS</div>
          <div className="truncate text-[11px] text-dim">
            <span className="hidden sm:inline">{clock.toLocaleDateString([], { weekday: "long", day: "numeric", month: "long" })} · </span>
            <span className="hidden min-[360px]:inline sm:hidden">{clock.toLocaleDateString([], { day: "numeric", month: "short" })} · </span>
            {clock.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </div>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-2">
        <button onClick={() => setPanel((p) => !p)} title="Voice and wake word" aria-label="Voice and wake word"
          className={`inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] ring-1 transition pointer-coarse:min-h-11 pointer-coarse:px-3.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/70 ${wakeOn ? "bg-violet/12 text-violet ring-violet/30 hover:bg-violet/20" : "bg-white/[0.05] text-dim ring-white/[0.08] hover:text-white"}`}>
          {wakeOn ? <motion.span className="h-1.5 w-1.5 rounded-full bg-violet" animate={{ opacity: [1, 0.3, 1] }} transition={{ duration: 1.6, repeat: Infinity }} /> : <Icon name="mic" className="h-3.5 w-3.5" />}
          {wakeOn ? <><span className="sm:hidden">Archu</span><span className="hidden sm:inline">Hello Archu</span></> : "Voice"}
        </button>
        <button onClick={() => { setUpdOpen((o) => !o); if (!updOpen && update.phase === "idle") checkUpdate(); }}
          title="Software update" aria-label={available ? "Software update available" : "Software update"}
          className={`relative inline-flex items-center gap-1.5 whitespace-nowrap rounded-full px-2.5 py-1 text-[11px] ring-1 transition pointer-coarse:min-h-11 pointer-coarse:px-3.5 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/70 ${available ? "bg-blue/15 text-[#7cb8ff] ring-blue/40 hover:bg-blue/25" : "bg-white/[0.05] text-dim ring-white/[0.08] hover:text-white"}`}>
          <Icon name="update" className="h-3.5 w-3.5" />
          <span className={available ? "" : "hidden md:inline"}>{update.phase === "done" ? "Restart" : available ? "Update" : "Updates"}</span>
          {available && <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-blue ring-2 ring-[#0c121b]" />}
        </button>
        {health?.dry_run && <span className="rounded-full bg-amber/15 px-2.5 py-1 text-[11px] font-semibold text-amber ring-1 ring-amber/30">DRY RUN</span>}
        <span className="hidden items-center gap-1.5 rounded-full bg-white/[0.05] px-2.5 py-1 text-[11px] text-dim ring-1 ring-white/[0.07] sm:inline-flex">
          <Icon name="shield" className="h-3.5 w-3.5" />
          {health ? `${health.llm_provider}${health.llm_model ? ` · ${health.llm_model}` : ""}` : "backend unreachable"}
        </span>
        <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] ring-1 ${connected ? "bg-mint/10 text-mint ring-mint/25" : "bg-rose/10 text-rose ring-rose/25"}`}>
          <span className={`h-1.5 w-1.5 rounded-full ${connected ? "bg-mint" : "bg-rose"}`} />
          {connected ? "Live" : "Offline"}
        </span>
        <AnimatePresence>
          {running && (
            <motion.button className="btn-red" onClick={onStop} initial={{ opacity: 0, scale: 0.8, width: 0 }} animate={{ opacity: 1, scale: 1, width: "auto" }} exit={{ opacity: 0, scale: 0.8, width: 0 }} transition={SPRING}>
              <Icon name="stop" className="h-3.5 w-3.5" /> Stop
            </motion.button>
          )}
        </AnimatePresence>
      </div>
      <AnimatePresence>{panel && voice && <VoicePanel view={voice} setView={setVoice} close={() => setPanel(false)} />}</AnimatePresence>
      <AnimatePresence>{updOpen && <UpdatePanel update={update} check={checkUpdate} apply={applyUpdate} close={() => setUpdOpen(false)} />}</AnimatePresence>
    </motion.header>
  );
}

function VoicePanel({ view, setView, close }: { view: PrefsView; setView: (v: PrefsView) => void; close: () => void }) {
  const [testing, setTesting] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const choose = async (id: string) => { try { setView(await api.setPrefs({ voice: id })); setMsg(null); } catch (e) { setMsg((e as Error).message); } };
  const test = async (id: string) => {
    setTesting(id); setMsg(null);
    try { const r = await api.testVoice(id); setMsg(r.fallback ? `Played with ${r.voice}: ${r.fallback}` : null); } catch (e) { setMsg((e as Error).message); }
    setTesting(null);
  };
  const toggleWake = async () => {
    try { setView(await api.setPrefs({ wake_enabled: !view.wake.running })); setMsg(null); } catch (e) { setMsg((e as Error).message); api.prefs().then(setView).catch(() => {}); }
  };
  // Portal: the header's backdrop blur makes its own stacking context, which put the panel under the cards.
  return createPortal(
    <>
      <motion.div className="fixed inset-0 z-40" onClick={close} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
      <motion.div className="glass-strong fixed right-3 top-[72px] z-50 max-h-[calc(100vh-90px)] w-[min(380px,calc(100vw-24px))] overflow-y-auto p-4 sm:right-6"
        initial={{ opacity: 0, y: -8, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8, scale: 0.97 }} transition={SPRING}>
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <div className="text-[14px] font-semibold">Wake word</div>
            <div className="text-[11.5px] text-dim">Say <span className="text-white">“Hello Archu”</span>, then your command, or both in one go.</div>
          </div>
          <button onClick={toggleWake} role="switch" aria-checked={view.wake.running} aria-label="Wake word" disabled={!view.stt_available}
            className={`relative h-7 w-12 shrink-0 rounded-full transition ${view.wake.running ? "bg-mint" : "bg-white/15"} disabled:opacity-40`}>
            <motion.span transition={SPRING} animate={{ left: view.wake.running ? 22 : 2 }} className="absolute top-0.5 h-6 w-6 rounded-full bg-white shadow" />
          </button>
        </div>
        <div className="mb-4 rounded-xl bg-black/30 px-3 py-2 text-[11.5px] text-dim ring-1 ring-white/[0.06]">
          {!view.stt_available ? "Speech to text is not installed (install.ps1 -Voice)."
            : view.wake.error ? <span className="text-rose-200">{view.wake.error}</span>
            : view.wake.running ? <>Listening on {view.wake.mic ?? "the default mic"} · audio stays on this PC{view.wake.last_heard ? <> · last heard: “{view.wake.last_heard}”</> : null}</>
            : "Off. The microphone is not in use."}
        </div>
        <div className="mb-2 text-[14px] font-semibold">Voice</div>
        <div className="space-y-1.5">
          {view.voices.map((v) => {
            const on = view.prefs.voice === v.id;
            return (
              <div key={v.id} className={`flex items-center gap-3 rounded-2xl px-3 py-2 ring-1 transition ${on ? "bg-violet/12 ring-violet/40" : "bg-white/[0.03] ring-white/[0.06] hover:bg-white/[0.06]"}`}>
                <button className="flex min-w-0 flex-1 items-center gap-3 text-left disabled:opacity-50" onClick={() => choose(v.id)} disabled={!v.available}>
                  <span className={`grid h-4 w-4 shrink-0 place-items-center rounded-full ring-2 ${on ? "ring-violet" : "ring-white/25"}`}>{on && <motion.span layoutId="voice-dot" className="h-2 w-2 rounded-full bg-violet" />}</span>
                  <span className="min-w-0">
                    <span className="block text-[13px] font-medium">{v.label} {v.online && <span className="ml-1 rounded-full bg-amber/15 px-1.5 py-px text-[11px] font-semibold uppercase tracking-wide text-amber">online</span>}</span>
                    <span className="block truncate text-[11px] text-dim" title={v.available ? v.detail : v.note}>{v.available ? v.detail : v.note}</span>
                  </span>
                </button>
                <button className="btn-ghost shrink-0 px-2.5" onClick={() => test(v.id)} disabled={!v.available || testing !== null} title="Play a sample" aria-label={`Play ${v.label} sample`}>
                  {testing === v.id ? <motion.span className="h-3 w-3 rounded-full border-2 border-white/30 border-t-white" animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: "linear" }} /> : <Icon name="play" className="h-3 w-3" />}
                </button>
              </div>
            );
          })}
        </div>
        <div className="mt-3 text-[11px] leading-snug text-slate-500">Online voices send the text JARVIS speaks to Microsoft's speech service. If one fails, an offline voice is used.</div>
        {(msg || view.last_fallback) && <div className="mt-2 rounded-xl bg-amber/10 px-3 py-2 text-[11.5px] text-amber ring-1 ring-amber/20">{msg ?? view.last_fallback}</div>}
      </motion.div>
    </>,
    document.body,
  );
}

function UpdatePanel({ update, check, apply, close }: { update: UpdateState; check: () => void; apply: () => void; close: () => void }) {
  const { info, checking, phase } = update;
  const desktop = desktopApi();
  const fmt = (d?: string) => (d ? new Date(d).toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" }) : "");
  const [restarting, setRestarting] = useState(false);
  const restart = async () => { setRestarting(true); try { await desktop?.restart(); } catch { setRestarting(false); } };
  return createPortal(
    <>
      <motion.div className="fixed inset-0 z-40" onClick={close} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} />
      <motion.div role="dialog" aria-label="Software update" className="glass-strong fixed right-3 top-[72px] z-50 max-h-[calc(100dvh-90px)] w-[min(400px,calc(100vw-24px))] overflow-y-auto p-5 sm:right-6"
        initial={{ opacity: 0, y: -8, scale: 0.97 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -8, scale: 0.97 }} transition={SPRING}>
        <div className="mb-4 flex items-center gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-cyan to-blue text-black"><Icon name="update" /></span>
          <div className="min-w-0">
            <div className="text-[15px] font-semibold">Software update</div>
            <div className="truncate text-[12px] text-dim">{info?.current ? `Installed: ${info.current.sha} · ${fmt(info.current.date)}` : "JARVIS"}</div>
          </div>
        </div>

        {phase === "applying" && (
          <div className="mb-3 rounded-2xl bg-black/30 p-3 ring-1 ring-white/[0.06]">
            <div className="mb-2 flex items-center gap-2 text-[13px] font-medium">
              <motion.span className="h-3.5 w-3.5 rounded-full border-2 border-cyan/25 border-t-cyan" animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: "linear" }} />
              Updating… keep JARVIS open
            </div>
            <ul className="space-y-1 text-[12px] text-dim">{update.log.map((l, i) => <li key={i}>{l}</li>)}</ul>
          </div>
        )}
        {phase === "done" && (
          <div className="mb-3 rounded-2xl bg-mint/10 p-3 text-[13px] ring-1 ring-mint/25">
            <div className="font-medium text-mint">Update installed</div>
            <div className="mt-1 text-[12px] text-slate-300">{desktop ? "Restart JARVIS to start using it." : "Restart JARVIS (stop.ps1, then start.ps1) to start using it."}</div>
            {desktop && <button className="btn-primary mt-3 w-full" onClick={restart} disabled={restarting}>{restarting ? "Restarting…" : "Restart now"}</button>}
          </div>
        )}
        {phase === "failed" && (
          <div className="mb-3 rounded-2xl bg-rose/10 p-3 text-[12px] text-rose-200 ring-1 ring-rose/25">
            <div className="font-medium">Update failed — nothing was changed.</div>
            <div className="mt-1 break-words text-rose-200/80">{update.error}</div>
          </div>
        )}

        {phase !== "applying" && phase !== "done" && (
          checking ? <div className="py-2 text-[13px] text-dim">Checking for updates…</div>
          : update.checkError ? <div className="rounded-2xl bg-amber/10 p-3 text-[12px] text-amber ring-1 ring-amber/20">{update.checkError}</div>
          : !info ? null
          : !info.supported ? <div className="rounded-2xl bg-white/[0.04] p-3 text-[12.5px] text-slate-300 ring-1 ring-white/[0.06]">{info.reason}</div>
          : (info.behind ?? 0) === 0 ? <div className="py-1 text-[13px]"><span className="font-medium text-mint">JARVIS is up to date.</span>{info.reason ? <div className="mt-1 text-[12px] text-dim">{info.reason}</div> : null}</div>
          : (
            <div>
              <div className="text-[13px] font-medium">{info.behind} update{info.behind === 1 ? "" : "s"} available</div>
              <ul className="no-scrollbar mt-2 max-h-48 space-y-1.5 overflow-y-auto">
                {info.commits?.map((c) => (
                  <li key={c.sha} className="rounded-xl bg-white/[0.04] px-3 py-2 ring-1 ring-white/[0.05]">
                    <div className="text-[12.5px] leading-snug text-slate-100">{c.subject}</div>
                    <div className="mt-0.5 font-mono text-[11px] text-dim">{c.sha} · {fmt(c.date)}</div>
                  </li>
                ))}
              </ul>
              {info.reason && <div className="mt-2 text-[12px] text-amber">{info.reason}</div>}
              <button className="btn-primary mt-3 w-full" onClick={apply} disabled={!info.can_update}>Update now</button>
            </div>
          )
        )}

        {phase !== "applying" && (
          <button className="btn-ghost mt-3 w-full" onClick={check} disabled={checking}>{checking ? "Checking…" : "Check for updates"}</button>
        )}
      </motion.div>
    </>,
    document.body,
  );
}

function Card({ title, icon, children, className = "", right, delay = 0 }: { title: string; icon: string; children: React.ReactNode; className?: string; right?: React.ReactNode; delay?: number }) {
  return (
    <motion.section className={`glass flex min-h-0 flex-col ${className}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ ...SPRING, delay }}>
      <div className="flex items-center justify-between px-4 pb-3 pt-4">
        <div className="eyebrow flex items-center gap-1.5"><Icon name={icon} className="h-3.5 w-3.5" />{title}</div>
        {right}
      </div>
      {children}
    </motion.section>
  );
}

function EmptyState({ onPick, disabled }: { onPick: (t: string) => void; disabled: boolean }) {
  return (
    <motion.div className="flex h-full flex-col items-center justify-center gap-5 py-10 text-center" initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ delay: 0.15 }}>
      <div>
        <div className="bg-gradient-to-r from-white via-cyan to-blue bg-clip-text text-3xl font-semibold tracking-tight text-transparent sm:text-4xl">How can I help?</div>
        <div className="mt-2 text-sm text-dim">Everyday commands run on-device with zero LLM calls. Press <kbd className="rounded bg-white/10 px-1.5 py-0.5 font-mono text-xs">/</kbd> to type.</div>
      </div>
      <div className="flex max-w-xl flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((s, i) => (
          <motion.button key={s} disabled={disabled} onClick={() => onPick(s)} className="btn-ghost"
            initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={{ ...SPRING, delay: 0.2 + i * 0.04 }} whileHover={{ y: -2 }} whileTap={{ scale: 0.96 }}>
            {s}
          </motion.button>
        ))}
      </div>
    </motion.div>
  );
}

function Bubble({ m, children }: { m: Msg; children?: React.ReactNode }) {
  if (m.role === "user")
    return <div className="max-w-[85%] rounded-[20px] rounded-br-md bg-gradient-to-br from-blue to-[#3d6dff] px-4 py-2.5 text-[14px] text-white shadow-[0_8px_24px_-10px] shadow-blue/70">{m.text}</div>;
  if (m.tone === "answer")
    return (
      <div className="max-w-[90%] rounded-[20px] rounded-bl-md bg-gradient-to-br from-cyan/15 to-blue/10 px-5 py-3.5 ring-1 ring-cyan/25">
        <div className="text-[17px] font-medium tracking-tight text-white">{m.text}</div>
        {children}
      </div>
    );
  const tone = m.tone === "error" ? "text-rose-200 ring-rose/25 bg-rose/[0.07]" : m.tone === "info" ? "text-slate-400 ring-white/[0.05] bg-white/[0.03] text-[12.5px]" : "text-slate-100 ring-white/[0.07] bg-white/[0.06]";
  return <div className={`max-w-[90%] whitespace-pre-wrap rounded-[20px] rounded-bl-md px-4 py-2.5 text-[14px] ring-1 ${tone}`}>{m.text}{children}</div>;
}

function TypingDots({ color }: { color: string }) {
  return (
    <div className="inline-flex items-center gap-1 rounded-[20px] rounded-bl-md bg-white/[0.06] px-4 py-3 ring-1 ring-white/[0.07]">
      {[0, 1, 2].map((i) => (
        <motion.span key={i} className="h-2 w-2 rounded-full" style={{ background: color }}
          animate={{ y: [0, -4, 0], opacity: [0.4, 1, 0.4] }} transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }} />
      ))}
    </div>
  );
}

function Composer({ inputRef, value, setValue, connected, onSend, onError }: {
  inputRef: React.RefObject<HTMLInputElement | null>; value: string; setValue: (v: string) => void; connected: boolean; onSend: () => void; onError: (m: string) => void;
}) {
  return (
    <form className="p-3 sm:p-4" onSubmit={(e) => { e.preventDefault(); onSend(); }}>
      <div className="flex items-center gap-1.5 rounded-full bg-black/35 p-1.5 pl-3.5 ring-1 sm:gap-2 sm:pl-5 ring-white/[0.08] transition focus-within:ring-cyan/40 focus-within:shadow-[0_0_0_6px_rgba(94,231,255,0.07)]">
        <Icon name="sparkle" className="hidden h-4 w-4 shrink-0 text-cyan/70 min-[360px]:block" />
        <input aria-label="Command" ref={inputRef} className="min-h-11 min-w-0 flex-1 bg-transparent py-2 text-base outline-none sm:text-[15px] placeholder:text-slate-500" placeholder={connected ? "Ask JARVIS anything…" : "Waiting for backend…"} value={value} onChange={(e) => setValue(e.target.value)} disabled={!connected} />
        <PushToTalk onError={onError} />
        <motion.button whileTap={{ scale: 0.9 }} className="grid h-11 w-11 shrink-0 place-items-center rounded-full bg-blue focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/70 text-white shadow-[0_6px_18px_-6px] shadow-blue transition hover:brightness-110 disabled:bg-white/10 disabled:text-slate-500 disabled:shadow-none" disabled={!connected || !value.trim()} aria-label="Send">
          <Icon name="send" className="h-4.5 w-4.5" strokeWidth={2.2} />
        </motion.button>
      </div>
    </form>
  );
}

function TaskCard({ run }: { run: Run | null }) {
  const done = run?.steps.filter((s) => s.status === "succeeded" || s.status === "skipped_dry_run").length ?? 0;
  const pct = run && run.steps.length ? (done / run.steps.length) * 100 : 0;
  return (
    <Card title="Current task" icon="bolt" delay={0.06}
      right={run && <StatusPill status={run.status} />}>
      <div className="px-4 pb-4">
        {!run ? <div className="text-sm text-dim">Nothing running.</div> : (
          <>
            <div className="mb-1 flex items-baseline justify-between gap-2">
              <div className="truncate text-[15px] font-medium capitalize">{pretty(run.workflow) ?? "LLM plan"}</div>
              <div className="shrink-0 text-[11px] text-dim">{run.route === "local" ? "on-device" : "planner"}</div>
            </div>
            <div className="mb-4 h-1 overflow-hidden rounded-full bg-white/[0.06]">
              <motion.div className={`h-full rounded-full ${run.status === "failed" ? "bg-rose" : "bg-gradient-to-r from-cyan to-blue"}`} animate={{ width: `${run.status === "succeeded" ? 100 : pct}%` }} transition={SPRING} />
            </div>
            <ol className="relative space-y-3">
              {run.steps.map((s, i) => (
                <motion.li key={`${run.execution_id}-${s.idx}`} className="relative flex gap-3" initial={{ opacity: 0, x: -8 }} animate={{ opacity: 1, x: 0 }} transition={{ ...SPRING, delay: i * 0.05 }}>
                  {i < run.steps.length - 1 && <span className="absolute left-[9px] top-6 h-[calc(100%-6px)] w-px bg-white/10" />}
                  <StepIcon status={s.status} />
                  <div className="min-w-0 pt-px">
                    <div className="font-mono text-[12.5px]">{s.tool}{s.attempts && s.attempts > 1 ? <span className="text-dim"> ×{s.attempts}</span> : null}</div>
                    <AnimatePresence>{s.detail && <motion.div initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: "auto" }} className="text-[11.5px] leading-snug text-dim">{s.detail}</motion.div>}</AnimatePresence>
                  </div>
                </motion.li>
              ))}
            </ol>
            {run.error && <div className="mt-3 rounded-xl bg-rose/10 px-3 py-2 text-xs text-rose-200 ring-1 ring-rose/20">{run.error}</div>}
          </>
        )}
      </div>
    </Card>
  );
}

function StatusPill({ status }: { status: string }) {
  const c = { running: "bg-cyan/12 text-cyan ring-cyan/25", succeeded: "bg-mint/12 text-mint ring-mint/25", failed: "bg-rose/12 text-rose ring-rose/25", cancelled: "bg-amber/12 text-amber ring-amber/25" }[status] ?? "bg-white/5 text-dim ring-white/10";
  return <motion.span key={status} initial={{ scale: 0.8, opacity: 0 }} animate={{ scale: 1, opacity: 1 }} transition={SPRING} className={`rounded-full px-2 py-0.5 text-[11px] font-semibold capitalize ring-1 ${c}`}>{status}</motion.span>;
}

function StepIcon({ status }: { status: string }) {
  if (status === "running")
    return <motion.span className="mt-0.5 h-[18px] w-[18px] shrink-0 rounded-full border-2 border-cyan/25 border-t-cyan" animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: "linear" }} />;
  if (status === "succeeded" || status === "skipped_dry_run" || status === "failed" || status === "cancelled") {
    const ok = status !== "failed" && status !== "cancelled";
    const bg = status === "succeeded" ? "bg-mint" : status === "skipped_dry_run" ? "bg-slate-500" : status === "failed" ? "bg-rose" : "bg-amber";
    return (
      <motion.span initial={{ scale: 0.4 }} animate={{ scale: 1 }} transition={{ type: "spring", stiffness: 500, damping: 18 }} className={`mt-0.5 grid h-[18px] w-[18px] shrink-0 place-items-center rounded-full text-black ${bg}`}>
        <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={3.2} strokeLinecap="round" strokeLinejoin="round">
          <motion.path d={ok ? "M5 12.5 10 17.5 19 7" : "M7 7l10 10M17 7 7 17"} initial={{ pathLength: 0 }} animate={{ pathLength: 1 }} transition={{ duration: 0.35, delay: 0.05 }} />
        </svg>
      </motion.span>
    );
  }
  return <span className="mt-0.5 h-[18px] w-[18px] shrink-0 rounded-full border-2 border-white/15" title={status} />;
}

function WorkflowsCard({ workflows, disabled, runWf }: { workflows: Workflow[]; disabled: boolean; runWf: (n: string) => unknown }) {
  const [q, setQ] = useState("");
  const shown = useMemo(() => workflows.filter((w) => `${w.name} ${w.canonical_intent ?? ""} ${w.aliases.join(" ")}`.toLowerCase().includes(q.toLowerCase())), [workflows, q]);
  return (
    <Card title={`Saved workflows · ${workflows.length}`} icon="repeat" className="max-h-[26rem] lg:max-h-[min(26rem,55vh)]" delay={0.09}>
      <div className="px-4 pb-2"><input className="field w-full" placeholder="Filter…" value={q} onChange={(e) => setQ(e.target.value)} /></div>
      <ul className="min-h-0 space-y-1 overflow-y-auto px-2 pb-3">
        <AnimatePresence initial={false}>
          {shown.map((w) => (
            <motion.li key={w.id} layout initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="group flex items-center gap-3 rounded-2xl px-2 py-2 transition hover:bg-white/[0.05]">
              <span className="grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-white/[0.06] text-cyan ring-1 ring-white/[0.06]"><Icon name={workflowIcon(w.name)} /></span>
              <div className="min-w-0 flex-1">
                <div className="truncate text-[13px] font-medium capitalize">{pretty(w.name)} <span className="font-normal text-slate-500">v{w.version}</span></div>
                <div className="truncate text-[11.5px] text-dim">{w.canonical_intent || w.aliases[0]}</div>
                {w.uses_llm_per_run && <div className="text-[11px] text-amber">uses LLM on every run · not free</div>}
              </div>
              <button className="btn-cyan shrink-0 opacity-70 transition group-hover:opacity-100" disabled={disabled} onClick={() => runWf(w.name)}>
                <Icon name="play" className="h-3 w-3" /> Run
              </button>
            </motion.li>
          ))}
        </AnimatePresence>
        {shown.length === 0 && <li className="px-2 py-2 text-sm text-dim">No match.</li>}
      </ul>
    </Card>
  );
}

function ActionBar({ action, onDone, runWf, send, say }: {
  action: RouteAction; onDone: () => void;
  runWf: (n: string, p?: Record<string, unknown>) => unknown; send: (t: string) => void; say: (r: Msg["role"], t: string) => void;
}) {
  const [value, setValue] = useState("");
  if (action.kind === "needs_input" && action.workflow && action.missing?.length) {
    const key = action.missing[0];
    return (
      <form className="mt-2.5 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (!value.trim()) return; onDone(); runWf(action.workflow!, { ...action.params, [key]: value.trim() }); }}>
        <input autoFocus className="field flex-1" placeholder={key} value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="btn-primary">OK</button>
      </form>
    );
  }
  if (action.kind === "confirm" && action.workflow) {
    return <div className="mt-2.5 flex gap-2"><button className="btn-primary" onClick={() => { onDone(); runWf(action.workflow!); }}>Yes</button><button className="btn-ghost" onClick={onDone}>No</button></div>;
  }
  if (action.kind === "choose") {
    return <div className="mt-2.5 flex flex-wrap gap-2">{action.options?.map((o, i) => (
      <button key={i} className="btn-ghost" onClick={() => { onDone(); runWf(o.workflow, o.params); }}>{o.command}</button>))}</div>;
  }
  if (action.kind === "offer_save" && action.execution_id) {
    return (
      <form className="mt-2.5 flex flex-wrap gap-2" onSubmit={async (e) => {
        e.preventDefault();
        try { await api.save(action.execution_id!, value || action.suggested_name!); onDone(); } catch (err) { say("jarvis", `Save failed: ${(err as Error).message}`); }
      }}>
        <input className="field flex-1 font-mono" placeholder={action.suggested_name} value={value} onChange={(e) => setValue(e.target.value.toLowerCase())} />
        <button className="btn-primary">Save</button><button type="button" className="btn-ghost" onClick={onDone}>No thanks</button>
      </form>
    );
  }
  if (action.kind === "retry" && action.command) {
    return <div className="mt-2.5"><button className="btn-ghost" onClick={() => { onDone(); send(action.command!); }}><Icon name="repeat" className="h-3.5 w-3.5" /> Retry</button></div>;
  }
  return null;
}

function ApprovalDialog({ approval }: { approval?: Approval }) {
  return (
    <AnimatePresence>
      {approval && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-md" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <motion.div className="glass-strong w-full max-w-lg p-6" initial={{ scale: 0.92, y: 20, opacity: 0 }} animate={{ scale: 1, y: 0, opacity: 1 }} exit={{ scale: 0.95, opacity: 0 }} transition={SPRING}>
            <div className="mb-4 flex items-center gap-3">
              <span className="grid h-10 w-10 place-items-center rounded-2xl bg-amber/15 text-amber ring-1 ring-amber/30"><Icon name="shield" className="h-5 w-5" /></span>
              <div>
                <div className="text-[15px] font-semibold">Approval needed</div>
                <div className="font-mono text-xs text-cyan">{approval.tool}</div>
              </div>
            </div>
            <pre className="mb-5 max-h-72 overflow-auto whitespace-pre-wrap rounded-2xl bg-black/40 p-4 text-[13px] leading-relaxed ring-1 ring-white/[0.06]">{approval.description}</pre>
            <div className="flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => api.approve(approval.approval_id, false)}>Deny</button>
              <button className="btn-primary" onClick={() => api.approve(approval.approval_id, true)}>Approve</button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function ClaudeCard({ job, connected, send }: { job: ClaudeJob; connected: boolean; send: (t: string) => void }) {
  const [reply, setReply] = useState("");
  const [open, setOpen] = useState(true);
  const running = job.status === "running";
  const who = job.target === "code" ? "Claude Code" : "claude.ai";
  const folder = job.cwd ? job.cwd.split(/[\\/]/).filter(Boolean).pop() : null;
  const steps = job.steps.slice(-5);
  return (
    <motion.section layout className="glass flex min-h-0 flex-col overflow-hidden" initial={{ opacity: 0, y: 12, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, scale: 0.96 }} transition={SPRING}>
      <button className="flex items-center justify-between px-4 pb-3 pt-4 text-left" onClick={() => setOpen((o) => !o)}>
        <div className="flex min-w-0 items-center gap-2.5">
          <span className="relative grid h-8 w-8 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-[#ff9a62] to-[#d97757] text-black">
            {running && <motion.span className="absolute inset-0 rounded-xl ring-2 ring-[#ff9a62]" animate={{ scale: [1, 1.35], opacity: [0.7, 0] }} transition={{ duration: 1.4, repeat: Infinity }} />}
            <Icon name="sparkle" className="relative h-4 w-4" strokeWidth={2.2} />
          </span>
          <div className="min-w-0 leading-tight">
            <div className="text-[13.5px] font-semibold">{who}</div>
            <div className="truncate text-[11px] text-dim">{[folder, job.mode, job.model].filter(Boolean).join(" · ") || (job.url ? "current chat" : "")}{running ? ` · ${job.elapsed_s}s` : ""}</div>
          </div>
        </div>
        <StatusPill status={job.status === "done" ? "succeeded" : job.status === "stopped" ? "cancelled" : job.status} />
      </button>
      <AnimatePresence initial={false}>
        {open && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="min-h-0 space-y-3 px-4 pb-4">
            <div className="rounded-2xl bg-white/[0.04] px-3 py-2 text-[12.5px] text-slate-300 ring-1 ring-white/[0.06]"><span className="text-dim">You: </span>{job.prompt}</div>
            {steps.length > 0 && (
              <ul className="space-y-1 font-mono text-[11px] text-dim">
                {steps.map((s, i) => (
                  <motion.li key={`${job.steps.length}-${i}`} initial={{ opacity: 0, x: -6 }} animate={{ opacity: 1, x: 0 }} className="truncate">
                    <span className={running && i === steps.length - 1 ? "text-cyan" : ""}>{running && i === steps.length - 1 ? "▶ " : "✓ "}{s}</span>
                  </motion.li>
                ))}
              </ul>
            )}
            {running && !job.result && <TypingDots color="#ff9a62" />}
            {job.status === "done" && job.answer && (
              <motion.div initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={SPRING}
                className="rounded-2xl bg-gradient-to-br from-[#ff9a62]/15 to-[#d97757]/10 px-3.5 py-3 text-[14px] font-medium leading-snug text-white ring-1 ring-[#ff9a62]/30">
                {job.answer}
              </motion.div>
            )}
            {job.error && job.status !== "done" && <div className="rounded-2xl bg-rose/10 px-3 py-2 text-[12.5px] text-rose-200 ring-1 ring-rose/20">{job.error}</div>}
            {(job.plan || job.result) && (running ? (
              <div className="max-h-40 overflow-y-auto whitespace-pre-wrap rounded-2xl bg-black/30 px-3 py-2.5 text-[12px] leading-relaxed text-slate-400 ring-1 ring-white/[0.06]">{job.result}</div>
            ) : (
              <details className="group rounded-2xl bg-black/30 ring-1 ring-white/[0.06]">
                <summary className="cursor-pointer list-none px-3 py-2 text-[11.5px] text-dim transition hover:text-white">
                  <span className="inline-block transition group-open:rotate-90">›</span> Full reply{job.plan ? " and plan" : ""}
                </summary>
                <div className="max-h-64 overflow-y-auto whitespace-pre-wrap px-3 pb-3 text-[12.5px] leading-relaxed text-slate-300">
                  {job.plan ? `Plan:\n${job.plan}${job.result ? `\n\n${job.result}` : ""}` : job.result}
                </div>
              </details>
            ))}
            {job.files.length > 0 && (
              <div className="flex flex-wrap gap-1.5">{job.files.slice(0, 8).map((f) => (
                <span key={f} className="rounded-full bg-mint/10 px-2 py-0.5 font-mono text-[10.5px] text-mint ring-1 ring-mint/20" title={f}>{f.split(/[\\/]/).pop()}</span>))}</div>
            )}
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); if (!reply.trim()) return; send(`tell claude${job.target === "code" ? " code" : ""} to ${reply.trim()}`); setReply(""); }}>
              <input className="field min-w-0 flex-1" placeholder={running ? "Wait for Claude to finish…" : "Tell Claude what to do next…"} value={reply} onChange={(e) => setReply(e.target.value)} disabled={!connected || running} />
              {running
                ? <button type="button" className="btn-red" onClick={() => send("stop claude")}><Icon name="stop" className="h-3.5 w-3.5" />Stop</button>
                : <button className="btn-primary" disabled={!reply.trim()}>Send</button>}
            </form>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.section>
  );
}

function Toasts({ toasts, dismiss }: { toasts: Toast[]; dismiss: (id: number) => void }) {
  return (
    <div className="pointer-events-none fixed right-4 top-[max(1rem,env(safe-area-inset-top))] z-50 flex w-[min(20rem,calc(100vw-2rem))] flex-col gap-2">
      <AnimatePresence>
        {toasts.map((t) => (
          <motion.div key={t.id} layout initial={{ opacity: 0, y: -20, scale: 0.95 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, x: 40 }} transition={SPRING}
            className="glass-strong pointer-events-auto flex items-start gap-3 p-4" onClick={() => dismiss(t.id)}>
            <span className={`grid h-9 w-9 shrink-0 place-items-center rounded-xl text-black ${t.icon === "sparkle" ? "bg-gradient-to-br from-[#ff9a62] to-[#d97757]" : t.icon === "mic" ? "bg-gradient-to-br from-violet to-[#5e5ce6]" : t.icon === "update" ? "bg-gradient-to-br from-cyan to-blue" : "bg-gradient-to-br from-amber to-[#ff9f0a]"}`}><Icon name={t.icon ?? "timer"} /></span>
            <div className="min-w-0"><div className="text-sm font-semibold">{t.title}</div><div className="text-[13px] text-slate-300">{t.body}</div></div>
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}

function UsagePanel({ usage }: { usage: Usage | null }) {
  if (!usage) return null;
  const purposes = Object.entries(usage.by_purpose);
  const unknown = purposes.some(([, p]) => p.calls_with_unknown_cost > 0);
  const total = purposes.reduce((s, [, p]) => s + (p.est_cost ?? 0), 0);
  const runs = usage.cache_hits + usage.cache_misses;
  const ratio = runs ? usage.cache_hits / runs : 0;
  return (
    <Card title="Usage" icon="bolt" delay={0.1} className="shrink-0">
      <div className="flex items-center gap-3 px-4">
        <Ring value={ratio} />
        <div className="grid flex-1 grid-cols-3 gap-2 text-center">
          <Stat label="Local" value={usage.cache_hits} />
          <Stat label="Via LLM" value={usage.cache_misses} />
          <Stat label="LLM calls" value={usage.planner_calls} />
        </div>
      </div>
      <details className="group px-4 pb-3 pt-2 text-[11px] text-dim">
        <summary className="flex cursor-pointer list-none items-center justify-between py-1 text-slate-300 marker:hidden [&::-webkit-details-marker]:hidden">
          <span>Est. cost: ${total.toFixed(2)}{unknown ? " + unknown" : ""}</span>
          <span className="text-dim transition group-open:rotate-90">›</span>
        </summary>
        <div className="space-y-1 pt-1">
        {purposes.map(([k, p]) => (
          <div key={k} className="flex flex-wrap justify-between gap-x-2 font-mono"><span>{k}</span><span className="text-right">{p.calls}× · {p.input_tokens}/{p.output_tokens} tok · {p.est_cost == null ? "cost ?" : `$${p.est_cost.toFixed(4)}`}</span></div>
        ))}
        {unknown && <div className="pt-1">Unknown = model prices not set in .env</div>}
        </div>
      </details>
    </Card>
  );
}

function Ring({ value }: { value: number }) {
  const r = 26, c = 2 * Math.PI * r;
  return (
    <div className="relative h-14 w-14 shrink-0" title="Share of runs served from saved workflows">
      <svg viewBox="0 0 64 64" className="h-full w-full -rotate-90">
        <circle cx="32" cy="32" r={r} fill="none" stroke="rgba(255,255,255,0.08)" strokeWidth="6" />
        <motion.circle cx="32" cy="32" r={r} fill="none" stroke="url(#ringGrad)" strokeWidth="6" strokeLinecap="round" strokeDasharray={c}
          initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - value) }} transition={{ duration: 1.2, ease: [0.22, 1, 0.36, 1] }} />
        <defs><linearGradient id="ringGrad" x1="0" x2="1"><stop offset="0" stopColor="#5ee7ff" /><stop offset="1" stopColor="#30d158" /></linearGradient></defs>
      </svg>
      <div className="absolute inset-0 grid place-items-center text-[13px] font-semibold">{Math.round(value * 100)}%</div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="text-lg font-semibold tracking-tight text-white"><Counter value={value} /></div>
      <div className="whitespace-nowrap text-[11px] text-dim">{label}</div>
    </div>
  );
}

function Counter({ value }: { value: number }) {
  const ref = useRef<HTMLSpanElement>(null);
  const prev = useRef(0);
  useEffect(() => {
    const controls = animate(prev.current, value, { duration: 0.8, ease: "easeOut", onUpdate: (v) => { if (ref.current) ref.current.textContent = String(Math.round(v)); } });
    prev.current = value;
    return () => controls.stop();
  }, [value]);
  return <span ref={ref}>{value}</span>;
}

function PushToTalk({ onError }: { onError: (m: string) => void }) {
  // Click to start, click again to stop. A ref (not state) holds the recorder so a stop
  // that lands while getUserMedia is still pending is not lost.
  const recRef = useRef<MediaRecorder | null>(null);
  const startingRef = useRef(false);
  const [mode, setMode] = useState<"idle" | "starting" | "rec" | "sending">("idle");
  const start = async () => {
    startingRef.current = true;
    setMode("starting");
    try {
      if (!window.isSecureContext || !navigator.mediaDevices) throw new Error("insecure");
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        setMode("sending");
        try {
          if (!chunks.length) throw new Error("no audio captured");
          await api.voice(new Blob(chunks, { type: mr.mimeType }));
        } catch (err) { onError(`Voice failed: ${(err as Error).message}. Text input still works.`); }
        setMode("idle");
      };
      mr.start();
      recRef.current = mr;
      setMode("rec");
    } catch {
      setMode("idle");
      onError("Microphone unavailable (open the dashboard at http://localhost:8765 and allow mic access). Text input still works.");
    } finally {
      startingRef.current = false;
    }
  };
  const stop = () => { recRef.current?.stop(); recRef.current = null; };
  const toggle = () => {
    if (startingRef.current || mode === "sending") return;
    if (recRef.current) stop(); else void start();
  };
  const rec = mode === "rec";
  return (
    <button type="button" onClick={toggle} disabled={mode === "sending"} title="Click to talk, click again to send" aria-label="Voice input"
      className={`relative grid h-11 w-11 shrink-0 place-items-center rounded-full transition focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/70 ${rec ? "bg-rose text-white" : "bg-white/[0.07] text-slate-300 hover:bg-white/[0.12] hover:text-white"} disabled:opacity-40`}>
      {rec && <motion.span className="absolute inset-0 rounded-full bg-rose" animate={{ scale: [1, 1.6], opacity: [0.5, 0] }} transition={{ duration: 1.1, repeat: Infinity }} />}
      {mode === "sending" ? <motion.span className="h-4 w-4 rounded-full border-2 border-white/30 border-t-white" animate={{ rotate: 360 }} transition={{ duration: 0.8, repeat: Infinity, ease: "linear" }} />
        : <Icon name={rec ? "stop" : "mic"} className="relative h-4.5 w-4.5" />}
    </button>
  );
}
