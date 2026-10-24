// Small SF-Symbols-like line icons (24px grid, stroke = currentColor).
const PATHS: Record<string, string> = {
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v4.5l3 2",
  cloud: "M7 18h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.1 9.5 4.25 4.25 0 0 0 7 18Z",
  mail: "M3.5 6.5h17v11h-17zM4 7l8 6 8-6",
  play: "M8 5.5v13l10.5-6.5z",
  pause: "M8 5v14M16 5v14",
  camera: "M4 8h3l1.5-2.5h7L17 8h3v11H4zM12 16.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z",
  timer: "M12 21a8 8 0 1 0 0-16 8 8 0 0 0 0 16Zm0-12v4l2.5 2.5M9.5 2.5h5",
  volume: "M4 9.5h3.5L12 6v12l-4.5-3.5H4zM15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11",
  note: "M6 3.5h9l3.5 3.5v13.5H6zM9 11h6M9 14.5h6M9 18h4",
  search: "M10.5 17.5a7 7 0 1 0 0-14 7 7 0 0 0 0 14ZM15.5 15.5 20.5 20.5",
  globe: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18ZM3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3Z",
  apps: "M4.5 4.5h6v6h-6zM13.5 4.5h6v6h-6zM4.5 13.5h6v6h-6zM13.5 13.5h6v6h-6z",
  map: "M9 4.5 3.5 6.5v13L9 17.5l6 2 5.5-2v-13L15 6.5zM9 4.5v13M15 6.5v13",
  pin: "M12 21s6.5-6.1 6.5-11.2A6.5 6.5 0 0 0 5.5 9.8C5.5 14.9 12 21 12 21Zm0-8.7a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z",
  bag: "M5 8h14l-1 12.5H6zM9 8V6.5a3 3 0 0 1 6 0V8",
  code: "M8.5 7 3.5 12l5 5M15.5 7l5 5-5 5",
  repeat: "M4 11V9a3 3 0 0 1 3-3h12l-3-3M20 13v2a3 3 0 0 1-3 3H5l3 3",
  bolt: "M13 3 5 13.5h6L10 21l8-10.5h-6z",
  mic: "M12 15a3.5 3.5 0 0 0 3.5-3.5v-5a3.5 3.5 0 1 0-7 0v5A3.5 3.5 0 0 0 12 15Zm-6.5-3.5a6.5 6.5 0 0 0 13 0M12 18v3",
  stop: "M7 7h10v10H7z",
  send: "M12 19V5M6 11l6-6 6 6",
  check: "M5 12.5 10 17.5 19 7",
  x: "M6 6l12 12M18 6 6 18",
  sparkle: "M12 3.5 13.8 10.2 20.5 12 13.8 13.8 12 20.5 10.2 13.8 3.5 12 10.2 10.2z",
  shield: "M12 3 4.5 6v5.5c0 4.6 3.2 8.4 7.5 9.5 4.3-1.1 7.5-4.9 7.5-9.5V6z",
  list: "M8.5 6.5h11M8.5 12h11M8.5 17.5h11M4.5 6.5h.01M4.5 12h.01M4.5 17.5h.01",
};

export function Icon({ name, className = "h-4 w-4", strokeWidth = 1.7 }: { name: string; className?: string; strokeWidth?: number }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden>
      <path d={PATHS[name] ?? PATHS.sparkle} />
    </svg>
  );
}

const WORKFLOW_ICONS: Record<string, string> = {
  youtube_play: "play", coding_workspace: "code", notion_meeting_notes: "note", directions: "map",
  maps_search: "pin", media_control: "volume", open_app: "apps", open_site: "globe", set_timer: "timer",
  site_search: "bag", claude_ask: "sparkle", claude_status: "sparkle", claude_stop: "stop", play_visible_video: "play",
  rotate_screen: "repeat", scroll_page: "list", set_volume: "volume", video_fullscreen: "apps", take_screenshot: "camera", tell_time: "clock", weather: "cloud", web_search: "search",
};

export const workflowIcon = (name: string) => WORKFLOW_ICONS[name] ?? "bolt";
