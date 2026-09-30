// ─────────────────────────────────────────────────────────────────────────────
// PESUcoin colour system.
//
// Two palettes with identical keys. Nothing in the interface names a colour by
// what it looks like ("navy", "cream"); everything names it by the job it does
// ("canvas", "anchor", "positive"), which is what lets the same component tree
// render correctly in both schemes.
//
// The light palette is the default and carries the product's character: a warm
// paper canvas, white cards, and a single deep anchor colour that does the
// heavy lifting on the balance card and primary actions. Both the anchor and
// the accent are taken from the PESUcoin mark itself - the navy of the coin's
// rim and the gold of its face - so the interface reads as this product rather
// than as a generic fintech template.
// ─────────────────────────────────────────────────────────────────────────────

export type Palette = {
  /** Page background. */
  canvas: string;
  /** A slightly deeper canvas, for grouped or inset regions. */
  canvasSunken: string;
  /** Card and sheet background. */
  surface: string;
  /** Nested surface inside a card, and input fields at rest. */
  surfaceAlt: string;
  /** Pressed and hovered surface. */
  surfaceHover: string;
  /** Translucent surface for the floating tab bar. */
  surfaceOverlay: string;

  /** Primary text. */
  ink: string;
  /** Supporting text. */
  inkSecondary: string;
  /** Labels, captions, metadata. */
  inkTertiary: string;
  /** Disabled and placeholder text. */
  inkDisabled: string;

  /**
   * The anchor as ink: icons, active states, small tinted fills. On dark this
   * has to be light enough to read against a near-black canvas.
   */
  anchor: string;
  /**
   * The anchor as a large filled surface: primary buttons and the brand action
   * tile. Kept deep in both schemes - a bright fill that works for a 20pt icon
   * becomes a slab of saturated colour at card size.
   */
  anchorSurface: string;
  /** Pressed anchor. */
  anchorPressed: string;
  /** Tinted anchor wash for chips and selected rows. */
  anchorSoft: string;
  anchorSoftBorder: string;
  /** Text and icons placed on the anchor colour. */
  onAnchor: string;
  /** Reduced-emphasis text on the anchor colour. */
  onAnchorMuted: string;
  /** Hairline on the anchor colour. */
  onAnchorHairline: string;

  /**
   * The balance card's three gradient stops: a deep navy warming towards
   * bronze at the far edge before settling back down. Held separately from
   * `anchor` because the card stays deep in both schemes, while `anchor`
   * lifts in dark mode so buttons stay legible.
   */
  heroFrom: string;
  heroVia: string;
  heroTo: string;

  /** Used sparingly: section overlines and the active tab. */
  accent: string;
  accentSoft: string;
  accentBorder: string;

  /** Money received. */
  positive: string;
  positiveSoft: string;
  positiveBorder: string;
  /** Money spent, destructive actions, errors. */
  negative: string;
  negativeSoft: string;
  negativeBorder: string;
  /** Needs attention, but nothing has failed. */
  warning: string;
  warningSoft: string;
  warningBorder: string;
  /** Informational, non-urgent. */
  info: string;
  infoSoft: string;
  infoBorder: string;

  /** Separators and card borders. */
  hairline: string;
  /** A border that needs to be seen, e.g. a secondary button. */
  hairlineStrong: string;
  /** Modal backdrop. */
  scrim: string;
  /** Skeleton placeholder fill. */
  placeholder: string;

  /**
   * Categorical series for charts, ordered by prominence. Warm and muted
   * rather than saturated, so a chart sits inside a card without shouting.
   */
  series: readonly [string, string, string, string, string];
};

export const lightPalette: Palette = {
  canvas: "#F4F2EC",
  canvasSunken: "#EDEAE1",
  surface: "#FFFFFF",
  surfaceAlt: "#F7F5EF",
  surfaceHover: "#EFEBE2",
  surfaceOverlay: "rgba(255,255,255,0.92)",

  ink: "#16202F",
  inkSecondary: "#565F6E",
  inkTertiary: "#818997",
  inkDisabled: "#A9AFB9",

  anchor: "#16305C",
  anchorSurface: "#16305C",
  anchorPressed: "#0F2445",
  anchorSoft: "rgba(22,48,92,0.08)",
  anchorSoftBorder: "rgba(22,48,92,0.16)",
  onAnchor: "#FFFFFF",
  onAnchorMuted: "rgba(255,255,255,0.68)",
  onAnchorHairline: "rgba(255,255,255,0.16)",

  heroFrom: "#20477F",
  heroVia: "#3A3526",
  heroTo: "#0B1424",

  accent: "#8F6212",
  accentSoft: "rgba(143,98,18,0.10)",
  accentBorder: "rgba(143,98,18,0.24)",

  positive: "#2E7D5A",
  positiveSoft: "rgba(46,125,90,0.10)",
  positiveBorder: "rgba(46,125,90,0.24)",
  negative: "#B03F2E",
  negativeSoft: "rgba(176,63,46,0.10)",
  negativeBorder: "rgba(176,63,46,0.24)",
  warning: "#A0700F",
  warningSoft: "rgba(160,112,15,0.12)",
  warningBorder: "rgba(160,112,15,0.26)",
  info: "#16305C",
  infoSoft: "rgba(22,48,92,0.08)",
  infoBorder: "rgba(22,48,92,0.18)",

  hairline: "rgba(22,32,47,0.08)",
  hairlineStrong: "rgba(22,32,47,0.16)",
  scrim: "rgba(20,24,30,0.42)",
  placeholder: "#E6E2D9",

  series: ["#1F4F42", "#A9761C", "#C7A03C", "#5B6478", "#B0AA9A"],
};

export const darkPalette: Palette = {
  // Cool, near-black canvas rather than neutral grey: the blue cast gives the
  // navy hero card something to sit against, and keeps the gold accent warm by
  // contrast instead of letting it drift orange.
  canvas: "#090B10",
  canvasSunken: "#05070A",
  surface: "#12161F",
  surfaceAlt: "#191F2A",
  surfaceHover: "#222936",
  surfaceOverlay: "rgba(18,22,31,0.94)",

  ink: "#F4F6FA",
  inkSecondary: "#AFB7C4",
  inkTertiary: "#828B99",
  inkDisabled: "#5C6472",

  // The hero card keeps its deep navy in both schemes; the anchor used for
  // buttons and active states lifts so it stays legible against a dark canvas.
  anchor: "#5A8EE6",
  anchorSurface: "#21467E",
  anchorPressed: "#4677C9",
  anchorSoft: "rgba(90,142,230,0.18)",
  anchorSoftBorder: "rgba(90,142,230,0.36)",
  onAnchor: "#FFFFFF",
  onAnchorMuted: "rgba(255,255,255,0.70)",
  onAnchorHairline: "rgba(255,255,255,0.16)",

  // Wider spread than the light card: on a dark canvas the gradient needs more
  // range before the eye reads it as depth rather than as one flat fill.
  heroFrom: "#22508F",
  heroVia: "#39331F",
  heroTo: "#060B14",

  accent: "#E3AE4A",
  accentSoft: "rgba(227,174,74,0.16)",
  accentBorder: "rgba(227,174,74,0.34)",

  positive: "#4ACB93",
  positiveSoft: "rgba(74,203,147,0.16)",
  positiveBorder: "rgba(74,203,147,0.32)",
  negative: "#F0776A",
  negativeSoft: "rgba(240,119,106,0.16)",
  negativeBorder: "rgba(240,119,106,0.32)",
  warning: "#E6B248",
  warningSoft: "rgba(230,178,72,0.16)",
  warningBorder: "rgba(230,178,72,0.32)",
  info: "#5A8EE6",
  infoSoft: "rgba(90,142,230,0.16)",
  infoBorder: "rgba(90,142,230,0.32)",

  // A shade stronger than light's hairlines: on a dark canvas a 7% border
  // disappears, and the card edges are what carry the depth here.
  hairline: "rgba(255,255,255,0.09)",
  hairlineStrong: "rgba(255,255,255,0.19)",
  scrim: "rgba(0,0,0,0.68)",
  placeholder: "#232A36",

  series: ["#46B394", "#E3AE4A", "#EBD07A", "#93A0BA", "#A8A091"],
};

export type ColorScheme = "light" | "dark";

export const palettes: Record<ColorScheme, Palette> = {
  light: lightPalette,
  dark: darkPalette,
};

/** The balance card's gradient stops, in draw order. */
export function heroGradient(palette: Palette): [string, string, string] {
  return [palette.heroFrom, palette.heroVia, palette.heroTo];
}
