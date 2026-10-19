import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, connectEvents, type JarvisEvent, type OrbState, type Usage, type Workflow } from "./api";
import { Orb } from "./Orb";

type Msg = { id: number; role: "user" | "jarvis"; text: string; action?: RouteAction };
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
type Run = { execution_id: string; steps: Step[]; status: string; error?: string | null; route?: string; workflow?: string | null };
type Approval = { approval_id: string; tool: string; description: string; execution_id: string };

let msgId = 0;

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
  const [input, setInput] = useState("");
  const lastCommand = useRef("");

  const say = useCallback((role: Msg["role"], text: string, action?: RouteAction) => {
    setMessages((m) => [...m.slice(-80), { id: ++msgId, role, text, action }]);
  }, []);
  const refresh = useCallback(() => {
    api.workflows().then(setWorkflows).catch(() => {});
    api.usage().then(setUsage).catch(() => {});
  }, []);

  const onEvent = useCallback(
    (e: JarvisEvent) => {
      const now = new Date().toLocaleTimeString();
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
            const how = e.route === "local" ? `local (${e.via || "direct"}), 0 planner calls` : "LLM planner";
            say("jarvis", `Running ${e.workflow ?? "a new plan"} via ${how}${e.reason ? ` — ${e.reason}` : ""}.`);
            setRun({ execution_id: e.execution_id, steps: e.steps.map((s: any, i: number) => ({ idx: i, tool: s.tool, status: "pending", args: s.args })), status: "running", route: e.route, workflow: e.workflow });
          } else if (e.kind === "needs_input") {
            say("jarvis", e.message, e.workflow ? { kind: "needs_input", workflow: e.workflow, params: e.params, missing: e.missing } : undefined);
          } else if (e.kind === "confirm") {
            say("jarvis", e.message, { kind: "confirm", workflow: e.workflow });
          } else if (e.kind === "choose") {
            say("jarvis", e.message, { kind: "choose", options: e.options });
          } else {
            say("jarvis", e.message || "I couldn't route that.", { kind: "retry", command: lastCommand.current });
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
          if (e.status === "succeeded") say("jarvis", e.dry_run ? "Dry run finished: every step validated, nothing was executed." : "Done. Every step was verified.");
          else say("jarvis", `Run ${e.status}: ${e.error ?? ""}`, e.status === "failed" ? { kind: "retry", command: lastCommand.current } : undefined);
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
          say("jarvis", `Saved workflow ${e.workflow.name} (v${e.workflow.version}). Next time it runs locally${e.workflow.uses_llm_per_run ? ", but it still calls an LLM on every run (UFO step)" : " with zero planner calls"}.`);
          refresh();
          break;
        case "transcript":
          say("user", `🎙 ${e.text}`);
          setActivity((a) => [...a.slice(-60), { t: now, text: `transcribed in ${e.latency_s}s` }]);
          break;
        case "warning":
          say("jarvis", `⚠ ${e.message}`);
          break;
      }
    },
    [say, refresh],
  );

  useEffect(() => connectEvents(onEvent, setConnected), [onEvent]);
  useEffect(() => {
    refresh();
    api.health().then(setHealth).catch(() => {});
  }, [refresh]);

  const send = async (text: string) => {
    if (!text.trim()) return;
    lastCommand.current = text;
    say("user", text);
    setInput("");
    try {
      await api.command(text);
    } catch (err) {
      say("jarvis", `Request failed: ${(err as Error).message}`, { kind: "retry", command: text });
    }
  };
  const runWf = (name: string, params: Record<string, unknown> = {}) =>
    api.runWorkflow(name, params).catch((err) => say("jarvis", `Request failed: ${err.message}`));
  const markDone = (id: number) => setMessages((m) => m.map((x) => (x.id === id && x.action ? { ...x, action: { ...x.action, done: true } } : x)));

  const running = run?.status === "running";

  return (
    <div className="mx-auto grid h-full max-w-[1500px] grid-cols-1 gap-4 p-4 lg:grid-cols-[1fr_1.4fr_1fr]">
      {/* Left: orb, workflows, usage */}
      <div className="flex min-h-0 flex-col gap-4">
        <div className="panel flex flex-col items-center gap-3 py-6">
          <Orb state={orb} connected={connected} />
          <div className="mt-6 text-center text-xs text-dim">
            {health ? `${health.llm_provider}${health.llm_model ? ` · ${health.llm_model}` : ""}${health.dry_run ? " · DRY RUN" : ""}` : "backend unreachable"}
          </div>
        </div>
        <div className="panel min-h-0 flex-1 overflow-auto">
          <div className="panel-title">Saved workflows</div>
          <ul className="space-y-2 px-4 pb-4">
            {workflows.map((w) => (
              <li key={w.id} className="flex items-center justify-between gap-2 rounded-lg border border-line px-3 py-2">
                <div className="min-w-0">
                  <div className="truncate font-mono text-sm">{w.name} <span className="text-dim">v{w.version}</span></div>
                  <div className="truncate text-xs text-dim">{w.aliases[0]}</div>
                  {w.uses_llm_per_run && <div className="text-xs text-amber-300">uses LLM on every run · not free</div>}
                </div>
                <button className="btn-cyan shrink-0" disabled={running} onClick={() => runWf(w.name)}>Run</button>
              </li>
            ))}
          </ul>
        </div>
        <UsagePanel usage={usage} />
      </div>

      {/* Middle: conversation + command box */}
      <div className="panel flex min-h-[60vh] flex-col">
        <div className="panel-title">Conversation</div>
        <div className="flex-1 space-y-3 overflow-auto px-4 pb-4">
          {messages.length === 0 && <div className="pt-10 text-center text-dim">Try “open my coding workspace for two-sum” or “play a video about python decorators”.</div>}
          <AnimatePresence initial={false}>
            {messages.map((m) => (
              <motion.div key={m.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className={m.role === "user" ? "text-right" : ""}>
                <div className={`inline-block max-w-[90%] whitespace-pre-wrap rounded-xl px-3 py-2 text-left text-sm ${m.role === "user" ? "bg-cyan/10 text-cyan" : "bg-white/5"}`}>
                  {m.text}
                  {m.action && !m.action.done && <ActionBar action={m.action} onDone={() => markDone(m.id)} runWf={runWf} send={send} say={say} />}
                </div>
              </motion.div>
            ))}
          </AnimatePresence>
        </div>
        <form className="flex gap-2 border-t border-line p-3" onSubmit={(e) => { e.preventDefault(); send(input); }}>
          <input className="flex-1 rounded-lg border border-line bg-bg px-3 py-2 text-sm outline-none focus:border-cyan/60" placeholder="Type a command…" value={input} onChange={(e) => setInput(e.target.value)} disabled={!connected} />
          <PushToTalk onError={(m) => say("jarvis", m)} />
          <button className="btn-cyan" disabled={!connected || !input.trim()}>Send</button>
        </form>
      </div>

      {/* Right: current task, tool activity */}
      <div className="flex min-h-0 flex-col gap-4">
        <div className="panel">
          <div className="flex items-center justify-between pr-3">
            <div className="panel-title">Current task</div>
            <button className="btn-red" disabled={!running} onClick={() => api.stop(run?.execution_id)}>Stop</button>
          </div>
          <div className="px-4 pb-4">
            {!run ? <div className="text-sm text-dim">Nothing running.</div> : (
              <>
                <div className="mb-2 text-sm"><span className="font-mono">{run.workflow ?? "LLM plan"}</span> <span className="text-dim">· {run.route} · {run.status}</span></div>
                <ol className="space-y-1.5">
                  {run.steps.map((s) => (
                    <li key={s.idx} className="flex gap-2 text-sm">
                      <StepDot status={s.status} />
                      <div className="min-w-0">
                        <div className="font-mono">{s.tool}{s.attempts && s.attempts > 1 ? <span className="text-dim"> ×{s.attempts}</span> : null}</div>
                        {s.detail && <div className="text-xs text-dim">{s.detail}</div>}
                      </div>
                    </li>
                  ))}
                </ol>
                {run.error && <div className="mt-2 text-xs text-red-300">{run.error}</div>}
              </>
            )}
          </div>
        </div>
        <div className="panel min-h-0 flex-1 overflow-auto">
          <div className="panel-title">Tool activity</div>
          <ul className="space-y-1 px-4 pb-4 font-mono text-xs">
            {activity.slice().reverse().map((a, i) => (
              <li key={i} className={a.ok === false ? "text-red-300" : a.ok ? "text-emerald-300" : "text-dim"}><span className="text-dim">{a.t}</span> {a.text}</li>
            ))}
          </ul>
        </div>
      </div>

      <ApprovalDialog approval={approvals[0]} />
    </div>
  );
}

function StepDot({ status }: { status: string }) {
  const color = { pending: "bg-slate-600", running: "bg-cyan animate-pulse", succeeded: "bg-emerald-400", skipped_dry_run: "bg-slate-400", failed: "bg-red-400", cancelled: "bg-amber-400" }[status] ?? "bg-slate-600";
  return <span className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${color}`} title={status} />;
}

function ActionBar({ action, onDone, runWf, send, say }: {
  action: RouteAction; onDone: () => void;
  runWf: (n: string, p?: Record<string, unknown>) => unknown; send: (t: string) => void; say: (r: Msg["role"], t: string) => void;
}) {
  const [value, setValue] = useState("");
  if (action.kind === "needs_input" && action.workflow && action.missing?.length) {
    const key = action.missing[0];
    return (
      <form className="mt-2 flex gap-2" onSubmit={(e) => { e.preventDefault(); if (!value.trim()) return; onDone(); runWf(action.workflow!, { ...action.params, [key]: value.trim() }); }}>
        <input autoFocus className="flex-1 rounded border border-line bg-bg px-2 py-1 text-sm" placeholder={key} value={value} onChange={(e) => setValue(e.target.value)} />
        <button className="btn-cyan">OK</button>
      </form>
    );
  }
  if (action.kind === "confirm" && action.workflow) {
    return <div className="mt-2 flex gap-2"><button className="btn-cyan" onClick={() => { onDone(); runWf(action.workflow!); }}>Yes</button><button className="btn-ghost" onClick={onDone}>No</button></div>;
  }
  if (action.kind === "choose") {
    return <div className="mt-2 flex flex-wrap gap-2">{action.options?.map((o, i) => (
      <button key={i} className="btn-ghost" onClick={() => { onDone(); runWf(o.workflow, o.params); }}>{o.command}</button>))}</div>;
  }
  if (action.kind === "offer_save" && action.execution_id) {
    return (
      <form className="mt-2 flex gap-2" onSubmit={async (e) => {
        e.preventDefault();
        try { await api.save(action.execution_id!, value || action.suggested_name!); onDone(); } catch (err) { say("jarvis", `Save failed: ${(err as Error).message}`); }
      }}>
        <input className="flex-1 rounded border border-line bg-bg px-2 py-1 font-mono text-sm" placeholder={action.suggested_name} value={value} onChange={(e) => setValue(e.target.value.toLowerCase())} />
        <button className="btn-cyan">Save</button><button type="button" className="btn-ghost" onClick={onDone}>No thanks</button>
      </form>
    );
  }
  if (action.kind === "retry" && action.command) {
    return <div className="mt-2"><button className="btn-ghost" onClick={() => { onDone(); send(action.command!); }}>Retry</button></div>;
  }
  return null;
}

function ApprovalDialog({ approval }: { approval?: Approval }) {
  return (
    <AnimatePresence>
      {approval && (
        <motion.div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}>
          <motion.div className="panel w-full max-w-lg p-5" initial={{ scale: 0.95 }} animate={{ scale: 1 }}>
            <div className="mb-1 text-xs uppercase tracking-[0.2em] text-amber-300">Approval needed</div>
            <div className="mb-3 font-mono text-cyan">{approval.tool}</div>
            <pre className="mb-4 max-h-72 overflow-auto whitespace-pre-wrap rounded-lg bg-bg p-3 text-sm">{approval.description}</pre>
            <div className="flex justify-end gap-2">
              <button className="btn-ghost" onClick={() => api.approve(approval.approval_id, false)}>Deny</button>
              <button className="btn-cyan" onClick={() => api.approve(approval.approval_id, true)}>Approve</button>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function UsagePanel({ usage }: { usage: Usage | null }) {
  if (!usage) return null;
  const purposes = Object.entries(usage.by_purpose);
  const unknown = purposes.some(([, p]) => p.calls_with_unknown_cost > 0);
  const total = purposes.reduce((s, [, p]) => s + (p.est_cost ?? 0), 0);
  return (
    <div className="panel">
      <div className="panel-title">Usage</div>
      <div className="grid grid-cols-3 gap-2 px-4 text-center">
        <Stat label="cache hits" value={usage.cache_hits} />
        <Stat label="misses" value={usage.cache_misses} />
        <Stat label="planner calls" value={usage.planner_calls} />
      </div>
      <div className="space-y-1 px-4 py-3 text-xs text-dim">
        {purposes.map(([k, p]) => (
          <div key={k} className="flex justify-between font-mono"><span>{k}</span><span>{p.calls}× · {p.input_tokens}/{p.output_tokens} tok · {p.est_cost == null ? "cost ?" : `$${p.est_cost.toFixed(4)}`}</span></div>
        ))}
        <div className="pt-1 text-slate-300">Est. total: ${total.toFixed(4)}{unknown ? " + unknown (prices not configured)" : ""}</div>
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return <div className="rounded-lg border border-line py-2"><div className="text-lg text-cyan">{value}</div><div className="text-[10px] uppercase tracking-wider text-dim">{label}</div></div>;
}

function PushToTalk({ onError }: { onError: (m: string) => void }) {
  const [rec, setRec] = useState<MediaRecorder | null>(null);
  const start = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      mr.ondataavailable = (e) => chunks.push(e.data);
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        try { await api.voice(new Blob(chunks, { type: mr.mimeType })); } catch (err) { onError(`Voice failed: ${(err as Error).message}. Text input still works.`); }
      };
      mr.start();
      setRec(mr);
    } catch {
      onError("Microphone unavailable. Text input still works.");
    }
  };
  const stop = () => { rec?.stop(); setRec(null); };
  return (
    <button type="button" className={rec ? "btn-red" : "btn-ghost"} onMouseDown={start} onMouseUp={stop} onMouseLeave={() => rec && stop()} onTouchStart={start} onTouchEnd={stop} title="Hold to talk">
      {rec ? "● Rec" : "🎙"}
    </button>
  );
}
