import { motion } from "framer-motion";
import type { OrbState } from "./api";

const COLORS: Record<OrbState, string> = {
  idle: "#22d3ee",
  listening: "#a78bfa",
  planning: "#facc15",
  executing: "#22d3ee",
  error: "#f87171",
};

// The orb only reflects state reported by the backend; it never guesses.
export function Orb({ state, connected }: { state: OrbState; connected: boolean }) {
  const color = connected ? COLORS[state] : "#475569";
  const busy = state === "executing" || state === "planning" || state === "listening";
  return (
    <div className="relative flex h-40 w-40 items-center justify-center">
      {[0, 1, 2].map((i) => (
        <motion.div
          key={i}
          className="absolute rounded-full"
          style={{ border: `1px solid ${color}`, width: 90 + i * 30, height: 90 + i * 30 }}
          animate={{ opacity: busy ? [0.15, 0.6, 0.15] : 0.18, scale: busy ? [1, 1.06, 1] : 1, rotate: busy ? 360 : 0 }}
          transition={{ duration: busy ? 1.6 + i * 0.5 : 0.4, repeat: busy ? Infinity : 0, ease: "easeInOut" }}
        />
      ))}
      <motion.div
        className="h-20 w-20 rounded-full"
        style={{ background: `radial-gradient(circle at 35% 35%, white, ${color} 45%, #031018 100%)`, boxShadow: `0 0 40px ${color}` }}
        animate={{ scale: state === "idle" ? [1, 1.04, 1] : state === "error" ? [1, 0.94, 1] : [1, 1.12, 1] }}
        transition={{ duration: state === "idle" ? 3 : 0.9, repeat: Infinity }}
      />
      <div className="absolute -bottom-6 text-xs uppercase tracking-[0.3em]" style={{ color }}>
        {connected ? state : "offline"}
      </div>
    </div>
  );
}
