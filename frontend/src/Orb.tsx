import { motion, useReducedMotion } from "framer-motion";
import type { OrbState } from "./api";

// Three blob colours per state, Siri-style.
export const PALETTE: Record<OrbState | "offline", [string, string, string]> = {
  idle: ["#5ee7ff", "#0a84ff", "#7d7aff"],
  listening: ["#bf5af2", "#ff375f", "#5e5ce6"],
  planning: ["#ffd60a", "#ff9f0a", "#bf5af2"],
  executing: ["#5ee7ff", "#30d158", "#0a84ff"],
  error: ["#ff453a", "#ff9f0a", "#ff375f"],
  offline: ["#3a4352", "#2a313d", "#4a5568"],
};

const LABEL: Record<OrbState, string> = {
  idle: "Ready",
  listening: "Listening",
  planning: "Thinking",
  executing: "Working",
  error: "Something went wrong",
};

// The orb only reflects state reported by the backend; it never guesses.
export function Orb({ state, connected, size = 168 }: { state: OrbState; connected: boolean; size?: number }) {
  const reduce = useReducedMotion();
  const key = connected ? state : "offline";
  const [a, b, c] = PALETTE[key];
  const busy = connected && (state === "executing" || state === "planning" || state === "listening");
  const speed = busy ? 1 : 3.2;

  return (
    <div className="flex flex-col items-center gap-5">
      <div className="relative" style={{ width: size, height: size }}>
        {/* soft halo */}
        <motion.div
          className="absolute -inset-10 rounded-full blur-3xl"
          style={{ background: `radial-gradient(circle, ${b}55, transparent 65%)` }}
          animate={reduce || !busy ? { scale: 1, opacity: 0.5 } : { scale: [1, 1.18, 1], opacity: [0.7, 1, 0.7] }}
          transition={{ duration: busy ? 1.4 : 4, repeat: Infinity, ease: "easeInOut" }}
        />
        {/* ripple rings while busy */}
        {busy && !reduce &&
          [0, 1].map((i) => (
            <motion.div
              key={i}
              className="absolute inset-0 rounded-full border"
              style={{ borderColor: `${a}80` }}
              initial={{ scale: 1, opacity: 0.6 }}
              animate={{ scale: 1.55, opacity: 0 }}
              transition={{ duration: 2, repeat: Infinity, delay: i, ease: "easeOut" }}
            />
          ))}
        {/* fluid core */}
        <div className="absolute inset-0 overflow-hidden rounded-full bg-[#060a12] shadow-[inset_0_0_30px_rgba(255,255,255,0.08)]">
          {[a, b, c].map((col, i) => (
            <motion.div
              key={i}
              className="absolute rounded-full mix-blend-screen blur-lg"
              style={{ width: "62%", height: "62%", left: `${10 + i * 14}%`, top: `${22 - i * 6 + (i === 2 ? 26 : 0)}%`, background: `radial-gradient(circle at 30% 30%, ${col}, transparent 70%)` }}
              animate={reduce || !busy ? undefined : {
                x: [0, (i - 1) * 22 + 14, -(i - 1) * 18 - 10, 0],
                y: [0, -16 + i * 10, 18 - i * 8, 0],
                scale: busy ? [1, 1.25, 0.9, 1] : [1, 1.08, 0.96, 1],
                rotate: [0, 120, 240, 360],
              }}
              transition={{ duration: (5 + i * 1.3) * (speed / 3.2) * (busy ? 1 : 1.6), repeat: Infinity, ease: "easeInOut" }}
            />
          ))}
          {/* glass highlight */}
          <div className="absolute inset-0 rounded-full bg-[radial-gradient(circle_at_32%_24%,rgba(255,255,255,0.55),transparent_32%)] mix-blend-overlay" />
          <div className="absolute inset-0 rounded-full ring-1 ring-inset ring-white/15" />
        </div>
      </div>
      <div className="flex items-center gap-2 text-sm font-medium" style={{ color: connected ? a : "#64748b" }}>
        <motion.span
          className="h-1.5 w-1.5 rounded-full"
          style={{ background: connected ? a : "#64748b" }}
          animate={busy && !reduce ? { opacity: [1, 0.3, 1] } : { opacity: 1 }}
          transition={{ duration: 1, repeat: Infinity }}
        />
        {connected ? LABEL[state] : "Offline"}
      </div>
    </div>
  );
}
