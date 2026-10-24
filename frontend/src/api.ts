export type OrbState = "idle" | "listening" | "planning" | "executing" | "error";

export interface Workflow {
  id: number;
  name: string;
  canonical_intent?: string;
  version: number;
  aliases: string[];
  params_schema: { required?: string[]; properties?: Record<string, unknown> };
  uses_llm_per_run: boolean;
  last_used_at: string | null;
}

export interface Usage {
  planner_calls: number;
  cache_hits: number;
  cache_misses: number;
  by_purpose: Record<
    string,
    { calls: number; input_tokens: number; output_tokens: number; est_cost: number | null; calls_with_unknown_cost: number }
  >;
}

export type JarvisEvent = { type: string; [k: string]: any };

export interface VoiceOption { id: string; label: string; detail: string; online: boolean; available: boolean; note: string }
export interface PrefsView {
  prefs: { voice: string; wake_enabled: boolean };
  voices: VoiceOption[];
  wake: { running: boolean; error: string | null; mic?: string | null; last_heard?: string | null };
  stt_available: boolean;
  last_voice: string | null;
  last_fallback: string | null;
}

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail ?? `${r.status}`);
  return data as T;
}

export type UpdateInfo = {
  supported: boolean; reason?: string | null; branch?: string; root?: string;
  current?: { sha: string; subject: string; date: string };
  behind?: number; ahead?: number; dirty?: boolean; can_update?: boolean;
  commits?: { sha: string; subject: string; date: string }[];
};

export const api = {
  command: (text: string) => req("POST", "/api/command", { text }),
  runWorkflow: (name: string, params: Record<string, unknown>) => req("POST", "/api/workflows/run", { name, params }),
  workflows: () => req<Workflow[]>("GET", "/api/workflows"),
  usage: () => req<Usage>("GET", "/api/usage"),
  health: () => req<{ status: string; dry_run: boolean; llm_provider: string; llm_model: string }>("GET", "/api/health"),
  approve: (approval_id: string, approved: boolean) => req("POST", "/api/approve", { approval_id, approved }),
  stop: (execution_id?: string) => req("POST", "/api/stop", { execution_id: execution_id ?? null }),
  prefs: () => req<PrefsView>("GET", "/api/prefs"),
  setPrefs: (p: { voice?: string; wake_enabled?: boolean }) => req<PrefsView>("POST", "/api/prefs", p),
  testVoice: (voice: string) => req<{ voice: string; fallback: string | null }>("POST", "/api/voice/test", { voice }),
  updateCheck: () => req<UpdateInfo>("GET", "/api/update/check"),
  updateApply: () => req("POST", "/api/update/apply"),
  save: (execution_id: string, name: string) => req<Workflow>("POST", "/api/workflows/save", { execution_id, name }),
  voice: async (blob: Blob) => {
    const fd = new FormData();
    fd.append("audio", blob, "speech.webm");
    const r = await fetch("/api/voice", { method: "POST", body: fd });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail ?? `${r.status}`);
    return data as { text: string; latency_s: number };
  },
};

export function connectEvents(onEvent: (e: JarvisEvent) => void, onStatus: (connected: boolean) => void): () => void {
  let ws: WebSocket | null = null;
  let closed = false;
  let retry: number | undefined;
  const open = () => {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    ws = new WebSocket(`${proto}://${location.host}/api/ws`);
    ws.onopen = () => onStatus(true);
    ws.onmessage = (m) => onEvent(JSON.parse(m.data));
    ws.onclose = () => {
      onStatus(false);
      if (!closed) retry = window.setTimeout(open, 1500);
    };
  };
  open();
  return () => {
    closed = true;
    window.clearTimeout(retry);
    ws?.close();
  };
}
