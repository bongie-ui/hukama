// Stroke icons on a 24px grid, drawn for Hukama. Decorative unless a label is given.

const PATHS: Record<string, string> = {
  home: "M4 11.5 12 5l8 6.5M6.5 10v9h11v-9M10 19v-5h4v5",
  shield: "M12 3.5 19 6v5.5c0 4.3-3 7.6-7 9-4-1.4-7-4.7-7-9V6l7-2.5Z M9 12l2 2 4-4",
  chat: "M5 6.5A2.5 2.5 0 0 1 7.5 4h9A2.5 2.5 0 0 1 19 6.5v7a2.5 2.5 0 0 1-2.5 2.5H11l-4.5 3.5V16h0A1.5 1.5 0 0 1 5 14.5Z",
  people: "M9 11a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Zm-6 9c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5M16 4.5a3.2 3.2 0 0 1 0 6.2M18 14.8c2 .7 3 2.4 3 5.2",
  plus: "M12 5v14M5 12h14",
  back: "M15 5l-7 7 7 7",
  chevron: "M9 6l6 6-6 6",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6 6 18",
  alert: "M12 4 21 19.5H3Z M12 10v4.5 M12 17.2v.3",
  clock: "M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Zm0-13v4.5l3 2",
  send: "M4.5 12 20 4.5 15 20l-3.5-6.5Zm7 1.5L20 4.5",
  camera: "M4 8.5A2.5 2.5 0 0 1 6.5 6h1.8l1.4-2h4.6l1.4 2h1.8A2.5 2.5 0 0 1 20 8.5v8a2.5 2.5 0 0 1-2.5 2.5h-11A2.5 2.5 0 0 1 4 16.5ZM12 16a3.2 3.2 0 1 0 0-6.4 3.2 3.2 0 0 0 0 6.4Z",
  clip: "M15.5 7.5 9 14a2 2 0 0 0 2.8 2.8l7-7a4 4 0 0 0-5.6-5.6l-7 7a6 6 0 0 0 8.5 8.5L19 15.5",
  phone: "M7 3.5h3l1.5 4-2 1.2a10 10 0 0 0 5.8 5.8l1.2-2 4 1.5v3A2.5 2.5 0 0 1 18 20.5 15 15 0 0 1 3.5 6 2.5 2.5 0 0 1 6 3.5Z",
  lock: "M7 10.5V8a5 5 0 0 1 10 0v2.5M5.5 10.5h13v9.5h-13Z M12 14.5v2",
  sparkle: "M12 3.5l1.8 4.7 4.7 1.8-4.7 1.8L12 16.5l-1.8-4.7L5.5 10l4.7-1.8ZM18.5 15.5l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8Z",
  doc: "M7 3.5h7l4 4V20.5H7Z M14 3.5V8h4 M9.5 12.5h6 M9.5 16h6",
  logout: "M14 4.5h4.5v15H14M10 8l-4 4 4 4M6 12h10",
  bolt: "M13 3 5 13.5h6L10 21l8-10.5h-6Z",
  chart: "M4 20.5h16M7 17v-5M12 17V7M17 17v-8",
  wallet: "M4 7.5A2.5 2.5 0 0 1 6.5 5h11V8M4 7.5v10A2.5 2.5 0 0 0 6.5 20H20v-12H6.5A2.5 2.5 0 0 1 4 7.5Zm12 6.5h.5",
  // Mandate types
  build: "M3.5 20.5h17M5 20.5V11l7-5 7 5v9.5M9.5 20.5V15h5v5.5",
  school: "M12 5 2.5 9.5 12 14l9.5-4.5Zm-6 6.8V16c0 1.7 2.7 3 6 3s6-1.3 6-3v-4.2M21.5 9.5V15",
  heart: "M12 19.5s-7.5-4.4-7.5-10A4.2 4.2 0 0 1 12 7a4.2 4.2 0 0 1 7.5 2.5c0 5.6-7.5 10-7.5 10Z",
  flower: "M12 13.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Zm0-5V4.5M12 13.5V20.5M9.5 11H5.5M18.5 11h-4M8 7l2.2 2.2M16 7l-2.2 2.2",
  health: "M12 3.5 19 6v5.5c0 4.3-3 7.6-7 9-4-1.4-7-4.7-7-9V6l7-2.5Z M12 8.5v6M9 11.5h6",
  // Products
  airtime: "M8 3.5h8v17H8Z M11 17.5h2",
  bundles: "M3.5 9.5a12 12 0 0 1 17 0M6.5 12.8a7.5 7.5 0 0 1 11 0M9.5 16a3 3 0 0 1 5 0M12 19v.2",
  cash: "M3.5 7h17v10h-17Z M12 14.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5Z M6.5 10v4M17.5 10v4",
};

export type IconName = keyof typeof PATHS;

export default function Icon({ name, size = 20, label, stroke = 1.8 }:
  { name: IconName | string; size?: number; label?: string; stroke?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={stroke}
      strokeLinecap="round" strokeLinejoin="round" role={label ? "img" : undefined} aria-label={label}
      aria-hidden={label ? undefined : true}>
      <path d={PATHS[name] ?? PATHS.doc} />
    </svg>
  );
}

export const TYPE_ICON: Record<string, IconName> = {
  AKHA: "build", IMFUNDO: "school", ISIKHWAMA: "heart", ISILILO: "flower", VIKELA: "health",
};
