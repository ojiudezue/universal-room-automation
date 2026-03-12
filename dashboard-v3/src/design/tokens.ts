/**
 * Design token system for URA v3 dashboard.
 * All color, spacing, typography, and animation values are defined here.
 * Components must reference tokens -- never use raw hex values.
 */

// -- Color Tokens --
export const color = {
  // Surface hierarchy
  surface: {
    base: "rgba(8, 8, 20, 0.92)",
    raised: "rgba(18, 18, 35, 0.82)",
    overlay: "rgba(22, 22, 40, 0.88)",
    scrim: "rgba(0, 0, 0, 0.5)",
  },

  // Text hierarchy (all meet 4.5:1+ on dark backgrounds)
  text: {
    primary: "rgba(255, 255, 255, 0.95)",    // 15.6:1
    secondary: "rgba(255, 255, 255, 0.72)",   // 10.8:1
    tertiary: "rgba(255, 255, 255, 0.52)",    // 7.8:1 (use only for non-essential info)
    disabled: "rgba(255, 255, 255, 0.32)",    // decorative only
  },

  // Semantic status colors
  status: {
    green: "#66BB6A",
    yellow: "#FFCA28",
    orange: "#FFA726",
    red: "#EF5350",
    blue: "#42A5F5",
    purple: "#AB47BC",
  },

  // Brand accent
  accent: {
    primary: "#82B1FF",
    primaryDim: "rgba(130, 177, 255, 0.16)",
    primaryGlow: "rgba(130, 177, 255, 0.25)",
  },

  // Glass effects
  glass: {
    bg: "rgba(18, 18, 35, 0.72)",
    border: "rgba(255, 255, 255, 0.08)",
    borderHover: "rgba(255, 255, 255, 0.14)",
    blur: "blur(20px) saturate(180%)",
  },
} as const;

// -- Spacing (4px base grid) --
export const space = {
  xs: 4,
  sm: 8,
  md: 12,
  lg: 16,
  xl: 20,
  "2xl": 24,
  "3xl": 32,
} as const;

// -- Typography --
export const type = {
  family: "-apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif",
  familyMono: "'SF Mono', 'Fira Code', 'Consolas', monospace",
  size: {
    xs: "0.7rem",     // 11.2px -- labels only
    sm: "0.78rem",    // 12.5px
    base: "0.85rem",  // 13.6px -- info rows
    md: "0.95rem",    // 15.2px -- card titles
    lg: "1.1rem",     // 17.6px -- section headers
    xl: "1.4rem",     // 22.4px -- key metrics
    "2xl": "2rem",    // 32px -- hero numbers
    "3xl": "2.8rem",  // 44.8px -- giant metrics
  },
  weight: {
    regular: 400,
    medium: 500,
    semibold: 600,
    bold: 700,
  },
  lineHeight: {
    tight: 1.1,
    normal: 1.4,
    relaxed: 1.6,
  },
} as const;

// -- Border Radius --
export const radius = {
  sm: 6,
  md: 10,
  lg: 14,
  xl: 18,
  full: 9999,
} as const;

// -- Breakpoints --
export const breakpoint = {
  sm: 480,
  md: 768,
  lg: 1024,
  xl: 1400,
} as const;

// -- Timing / Animation --
export const timing = {
  fast: "150ms",
  normal: "200ms",
  slow: "300ms",
  easeOut: "cubic-bezier(0.0, 0.0, 0.2, 1)",
  easeIn: "cubic-bezier(0.4, 0.0, 1, 1)",
  spring: "cubic-bezier(0.34, 1.56, 0.64, 1)",
} as const;

// -- Z-Index layers --
export const zIndex = {
  base: 0,
  card: 1,
  sticky: 10,
  tabBar: 100,
  overlay: 200,
  modal: 300,
  toast: 400,
} as const;

// -- Status color mapping for HA entity states --
export const stateColorMap: Record<string, string> = {
  // Energy TOU
  off_peak: color.status.green,
  mid_peak: color.status.yellow,
  peak: color.status.red,

  // HVAC modes
  normal: color.status.green,
  coast: color.status.yellow,
  pre_cool: color.status.blue,
  pre_heat: color.status.orange,
  shed: color.status.red,

  // House states
  home_day: color.status.green,
  home_evening: color.status.green,
  home_night: color.status.blue,
  sleep: color.status.blue,
  away: color.status.yellow,
  vacation: color.status.orange,
  arriving: color.status.green,
  waking: color.status.green,
  guest: color.status.green,

  // Generic
  active: color.status.green,
  idle: color.status.green,
  disabled: color.text.disabled,
  on: color.status.green,
  off: color.text.disabled,
  home: color.status.green,
  not_home: color.status.yellow,
  unknown: color.text.disabled,
  unavailable: color.text.disabled,

  // Health
  excellent: color.status.green,
  good: color.status.green,
  fair: color.status.yellow,
  poor: color.status.orange,
  very_poor: color.status.red,

  // Security
  armed_home: color.status.blue,
  armed_away: color.status.red,
  armed_night: color.status.blue,
  disarmed: color.status.green,
  pending: color.status.yellow,
  triggered: color.status.red,

  // Energy battery
  self_consumption: color.status.green,
  reserve: color.status.blue,
  grid_charge: color.status.yellow,
  grace_period: color.status.yellow,
  compromise: color.status.orange,
};
