import type { TextStyle } from "react-native";

// Non-colour tokens, ported from the PESUcoin design system (closed-loop-currency/frontend/src/theme/metrics.ts)
// and trimmed to what a web app needs.

export const spacing = { xxs: 2, xs: 4, sm: 8, ms: 12, md: 16, lg: 24, xl: 32, xxl: 44, xxxl: 64 } as const;
export const radii = { xs: 8, sm: 12, md: 16, lg: 22, xl: 28, pill: 999 } as const;

export const motion = {
  duration: { instant: 90, fast: 150, normal: 220, slow: 320 },
  spring: {
    press: { tension: 380, friction: 22 },
    enter: { tension: 180, friction: 20 },
  },
  stagger: 40,
} as const;

export const layout = { contentMaxWidth: 1200, formMaxWidth: 680, controlHeight: 40, controlHeightSm: 32, barHeight: 64 } as const;

export type ElevationLevel = "none" | "sm" | "md" | "lg";

// Depth is shadow on light and surface lightness plus a hairline on dark, so each scheme gets its own ramp.
export const elevationByScheme = {
  light: {
    none: "none",
    sm: "0 1px 3px rgba(42,36,24,0.05)",
    md: "0 4px 14px rgba(42,36,24,0.07)",
    lg: "0 10px 26px rgba(42,36,24,0.10), 0 0 0 1px rgba(22,32,47,0.08)",
  },
  dark: {
    none: "none",
    sm: "0 1px 3px rgba(0,0,0,0.28)",
    md: "0 4px 14px rgba(0,0,0,0.34)",
    lg: "0 10px 26px rgba(0,0,0,0.42), 0 0 0 1px rgba(255,255,255,0.19)",
  },
} as const;

const tabular: Pick<TextStyle, "fontVariant"> = { fontVariant: ["tabular-nums"] };
export const fontFamily =
  '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI Variable Text", "Segoe UI", Roboto, system-ui, sans-serif';
export const monoFamily = 'ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace';

const t = (fontSize: number, lineHeight: number, fontWeight: TextStyle["fontWeight"], letterSpacing = 0): TextStyle => ({
  fontFamily, fontSize, lineHeight, fontWeight, letterSpacing,
});

export const typography = {
  display: t(34, 39, "700", -1.1),
  title1: t(27, 32, "700", -0.7),
  title2: t(21, 27, "700", -0.5),
  title3: t(17, 23, "700", -0.3),
  headline: t(16, 22, "600", -0.2),
  body: t(15, 22, "400", -0.1),
  bodyStrong: t(15, 22, "600", -0.1),
  callout: t(15, 20, "500", -0.1),
  subheadline: t(14, 20, "400", -0.05),
  footnote: t(13, 18, "400"),
  caption: t(12, 16, "500"),
  overline: { ...t(11, 14, "700", 1.1), textTransform: "uppercase" } as TextStyle,
  metric: { ...t(28, 34, "700", -0.9), ...tabular } as TextStyle,
  numeric: { ...t(15, 20, "600", -0.2), ...tabular } as TextStyle,
  mono: { ...t(12.5, 19, "400"), fontFamily: monoFamily } as TextStyle,
} as const;

export type TypographyVariant = keyof typeof typography;
