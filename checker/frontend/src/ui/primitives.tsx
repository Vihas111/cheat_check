import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  Animated,
  Pressable,
  Text,
  TextInput,
  View,
  type StyleProp,
  type TextInputProps,
  type TextProps,
  type TextStyle,
  type ViewStyle,
} from "react-native";
import Svg, { Circle, Path } from "react-native-svg";

import { fontFamily, motion, radii, spacing, typography, type ElevationLevel, type TypographyVariant } from "../theme";
import type { Palette } from "../theme/palette";
import { useColors, useTheme } from "../theme";

/** Style props that exist on the web but not in React Native's types (cursor, position: fixed, ...). */
export const web = (s: Record<string, unknown>) => s as unknown as ViewStyle;

type ColorKey = { [K in keyof Palette]: Palette[K] extends string ? K : never }[keyof Palette];

// ---------- text ----------

export function T({ v = "body", c = "ink", style, ...rest }: TextProps & { v?: TypographyVariant; c?: ColorKey }) {
  const colors = useColors();
  return <Text {...rest} style={[typography[v], { color: colors[c] as string }, style]} />;
}

// ---------- icons ----------

const PATHS: Record<string, string> = {
  down: "M6 9l6 6 6-6",
  up: "M18 15l-6-6-6 6",
  right: "M9 6l6 6-6 6",
  left: "M15 6l-6 6 6 6",
  moon: "M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z",
  upload: "M12 16V4M6 10l6-6 6 6M4 20h16",
  download: "M12 4v12M6 10l6 6 6-6M4 20h16",
  check: "M5 12l5 5 10-10",
  close: "M6 6l12 12M18 6L6 18",
  plus: "M12 5v14M5 12h14",
  sun: "M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  file: "M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8zM14 3v5h5",
  alert: "M12 8v5M12 16.5v.5M10.3 3.9L2.5 17.5A2 2 0 0 0 4.2 20.5h15.6a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z",
};

export function Icon({ name, size = 18, color }: { name: string; size?: number; color: string }) {
  return (
    <Svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color} strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
      {name === "sun" && <Circle cx={12} cy={12} r={4} />}
      {name === "system" && (
        <>
          <Circle cx={12} cy={12} r={8} />
          <Path d="M12 4a8 8 0 0 1 0 16z" fill={color} />
        </>
      )}
      {name === "search" && (
        <>
          <Circle cx={11} cy={11} r={7} />
          <Path d="M20 20l-4-4" />
        </>
      )}
      {PATHS[name] && <Path d={PATHS[name]} />}
    </Svg>
  );
}

// ---------- motion ----------

/** Fades and lifts its children in with a spring. Once settled it stops styling, so it never traps `position: fixed`. */
export function Reveal({ children, delay = 0, y = 10, x = 0, style }: { children: ReactNode; delay?: number; y?: number; x?: number; style?: StyleProp<ViewStyle> }) {
  const v = useRef(new Animated.Value(0)).current;
  const [settled, setSettled] = useState(false);
  useEffect(() => {
    const a = Animated.spring(v, { toValue: 1, ...motion.spring.enter, delay, useNativeDriver: false });
    a.start(({ finished }) => finished && setSettled(true));
    return () => a.stop();
  }, [v, delay]);
  const anim = settled
    ? undefined
    : { opacity: v, transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [y, 0] }) }, { translateX: v.interpolate({ inputRange: [0, 1], outputRange: [x, 0] }) }] };
  return <Animated.View style={[style, anim as object]}>{children}</Animated.View>;
}

/** Scales its child down slightly while pressed, like a physical key. */
function usePressScale(to = 0.97) {
  const s = useRef(new Animated.Value(1)).current;
  const spring = (v: number) => Animated.spring(s, { toValue: v, ...motion.spring.press, useNativeDriver: false }).start();
  return { style: { transform: [{ scale: s }] }, onPressIn: () => spring(to), onPressOut: () => spring(1) };
}

// ---------- buttons ----------

export type ButtonVariant = "primary" | "tonal" | "plain" | "danger" | "outline";

export function Button({ label, onPress, variant = "tonal", small, disabled, loading, icon, iconRight, style, title }: {
  label: string; onPress?: () => void; variant?: ButtonVariant; small?: boolean; disabled?: boolean; loading?: boolean;
  icon?: string; iconRight?: boolean; style?: StyleProp<ViewStyle>; title?: string;
}) {
  const c = useColors();
  const press = usePressScale();
  const scheme: Record<ButtonVariant, { bg: string; hover: string; fg: string; border?: string }> = {
    primary: { bg: c.anchorSurface, hover: c.anchorPressed, fg: c.onAnchor },
    tonal: { bg: c.anchorSoft, hover: c.anchorSoftBorder, fg: c.anchor },
    plain: { bg: "transparent", hover: c.surfaceHover, fg: c.anchor },
    danger: { bg: c.negativeSoft, hover: c.negativeBorder, fg: c.negative },
    outline: { bg: "transparent", hover: c.surfaceHover, fg: c.ink, border: c.hairlineStrong },
  };
  const s = scheme[variant];
  const off = disabled || loading;
  return (
    <Animated.View style={[press.style, off && { opacity: 0.45 }, style]}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel={title ?? label}
        disabled={off}
        onPress={onPress}
        onPressIn={press.onPressIn}
        onPressOut={press.onPressOut}
        // @ts-expect-error web-only prop
        title={title}
        style={({ hovered, pressed }) =>
          web({
            flexDirection: "row", alignItems: "center", justifyContent: "center", gap: 6,
            height: small ? 32 : 40, paddingHorizontal: small ? 14 : 18, borderRadius: radii.pill,
            backgroundColor: pressed || hovered ? s.hover : s.bg, borderWidth: s.border ? 1 : 0, borderColor: s.border,
            cursor: off ? "not-allowed" : "pointer", transitionProperty: "background-color", transitionDuration: "150ms",
          })
        }
      >
        {icon && !iconRight ? <Icon name={icon} size={small ? 15 : 17} color={s.fg} /> : null}
        <Text style={[typography.callout, { color: s.fg, fontWeight: "600", fontSize: small ? 13 : 14 }]} numberOfLines={1}>
          {loading ? "Working…" : label}
        </Text>
        {icon && iconRight ? <Icon name={icon} size={small ? 15 : 17} color={s.fg} /> : null}
      </Pressable>
    </Animated.View>
  );
}

export function IconButton({ icon, onPress, label, size = 40 }: { icon: string; onPress: () => void; label: string; size?: number }) {
  const c = useColors();
  const press = usePressScale(0.9);
  return (
    <Animated.View style={press.style}>
      <Pressable
        accessibilityRole="button" accessibilityLabel={label} onPress={onPress} onPressIn={press.onPressIn} onPressOut={press.onPressOut}
        // @ts-expect-error web-only prop
        title={label}
        style={({ hovered }) => web({ width: size, height: size, borderRadius: radii.pill, alignItems: "center", justifyContent: "center", backgroundColor: hovered ? c.surfaceHover : "transparent", cursor: "pointer" })}
      >
        <Icon name={icon} color={c.anchor} />
      </Pressable>
    </Animated.View>
  );
}

/** A pressable block that navigates or acts, with hover and press feedback. */
export function Tappable({ onPress, children, style, label }: { onPress: () => void; children: ReactNode; style?: StyleProp<ViewStyle>; label?: string }) {
  const c = useColors();
  return (
    <Pressable
      accessibilityRole="button" accessibilityLabel={label} onPress={onPress}
      style={({ hovered, pressed }) => [web({ cursor: "pointer", backgroundColor: pressed ? c.surfaceHover : hovered ? c.surfaceAlt : "transparent", transitionProperty: "background-color", transitionDuration: "120ms" }), style]}
    >
      {children}
    </Pressable>
  );
}

/** Text that looks and behaves like a link. */
export function LinkText({ children, onPress, style, v = "body" }: { children: ReactNode; onPress: () => void; style?: StyleProp<TextStyle>; v?: TypographyVariant }) {
  const c = useColors();
  return (
    <Text accessibilityRole="link" onPress={onPress} style={[typography[v], web({ color: c.anchor, cursor: "pointer" }) as TextStyle, style]}>
      {children}
    </Text>
  );
}

// ---------- surfaces ----------

export function Card({ children, style, pad = spacing.lg, elevation = "sm" }: { children: ReactNode; style?: StyleProp<ViewStyle>; pad?: number; elevation?: ElevationLevel }) {
  const c = useColors();
  const { shadow } = useTheme();
  return (
    <View style={[{ backgroundColor: c.surface, borderRadius: radii.md, borderWidth: 1, borderColor: c.hairline, padding: pad }, web(shadow(elevation)), style]}>
      {children}
    </View>
  );
}

export function Pill({ label, tone = "neutral" }: { label: string; tone?: "neutral" | "anchor" | "positive" | "warning" | "negative" }) {
  const c = useColors();
  const map = {
    neutral: [c.surfaceAlt, c.inkSecondary, c.hairline], anchor: [c.anchorSoft, c.anchor, "transparent"],
    positive: [c.positiveSoft, c.positive, "transparent"], warning: [c.warningSoft, c.warning, "transparent"],
    negative: [c.negativeSoft, c.negative, "transparent"],
  }[tone];
  return (
    <View style={{ alignSelf: "flex-start", height: 24, paddingHorizontal: 10, borderRadius: radii.pill, backgroundColor: map[0], borderWidth: 1, borderColor: map[2], justifyContent: "center" }}>
      <Text style={[typography.caption, { color: map[1] }]} numberOfLines={1}>{label}</Text>
    </View>
  );
}

/** Similarity suggestions are dashed; decisions are solid. */
export function Tier({ tier, label }: { tier: string; label: string }) {
  const c = useColors();
  const color = { HIGH: c.negative, MEDIUM: c.warning, LOW: c.positive, SEED: c.inkSecondary, REF: c.series[3] }[tier] ?? c.inkSecondary;
  return (
    <View style={{ alignSelf: "flex-start", height: 22, paddingHorizontal: 8, borderRadius: 6, borderWidth: 1, borderStyle: "dashed", borderColor: color, justifyContent: "center" }}>
      <Text style={[typography.caption, { color }]} numberOfLines={1}>{label}</Text>
    </View>
  );
}

export function Dot({ color }: { color: string }) {
  return <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: color }} />;
}

export function ProgressBar({ value, height = 4 }: { value: number; height?: number }) {
  const c = useColors();
  const v = useRef(new Animated.Value(value)).current;
  useEffect(() => {
    Animated.timing(v, { toValue: Math.max(0, Math.min(100, value)), duration: motion.duration.slow, useNativeDriver: false }).start();
  }, [v, value]);
  return (
    <View style={{ height, borderRadius: height / 2, backgroundColor: c.surfaceAlt, overflow: "hidden" }}>
      <Animated.View style={{ height, borderRadius: height / 2, backgroundColor: c.anchor, width: v.interpolate({ inputRange: [0, 100], outputRange: ["0%", "100%"] }) }} />
    </View>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <View style={{ padding: spacing.xxl, alignItems: "center" }}>
      <T c="inkSecondary" style={{ textAlign: "center" }}>{children}</T>
    </View>
  );
}

export function Hairline() {
  const c = useColors();
  return <View style={{ height: 1, backgroundColor: c.hairline }} />;
}

// ---------- inputs ----------

export function useFocusRing() {
  const c = useColors();
  const [focused, setFocused] = useState(false);
  return {
    handlers: { onFocus: () => setFocused(true), onBlur: () => setFocused(false) },
    style: web({ borderColor: focused ? c.anchor : c.hairline, boxShadow: focused ? `0 0 0 3px ${c.anchorSoft}` : "none", outlineStyle: "none", transitionProperty: "border-color, box-shadow", transitionDuration: "150ms" }),
  };
}

export function Label({ label, hint, children }: { label?: string; hint?: string; children: ReactNode }) {
  return (
    <View style={{ gap: 6 }}>
      {label ? <T v="footnote" style={{ fontWeight: "600" }}>{label}</T> : null}
      {hint ? <T v="footnote" c="inkSecondary" style={{ marginTop: -2 }}>{hint}</T> : null}
      {children}
    </View>
  );
}

export function Field({ label, hint, rows, style, ...props }: TextInputProps & { label?: string; hint?: string; rows?: number }) {
  const c = useColors();
  const ring = useFocusRing();
  return (
    <Label label={label} hint={hint}>
      <TextInput
        accessibilityLabel={label}
        {...props}
        {...ring.handlers}
        multiline={!!rows}
        numberOfLines={rows}
        placeholderTextColor={c.inkDisabled}
        style={[typography.body, { color: c.ink, backgroundColor: c.surfaceAlt, borderWidth: 1, borderRadius: radii.sm, paddingHorizontal: 12, paddingVertical: 9, minHeight: rows ? rows * 22 + 20 : 42 }, ring.style, style]}
      />
    </Label>
  );
}

/** Date and time entry uses the browser's own picker. */
export function DateField({ label, hint, value, onChange }: { label: string; hint?: string; value: string; onChange: (v: string) => void }) {
  const c = useColors();
  const ring = useFocusRing();
  return (
    <Label label={label} hint={hint}>
      <View style={[{ borderWidth: 1, borderRadius: radii.sm, backgroundColor: c.surfaceAlt }, ring.style]}>
        <input
          type="datetime-local"
          aria-label={label}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onFocus={ring.handlers.onFocus}
          onBlur={ring.handlers.onBlur}
          style={{ fontFamily, fontSize: 15, color: c.ink, background: "transparent", border: 0, outline: "none", padding: "0 12px", height: 40, width: "100%", boxSizing: "border-box", colorScheme: "inherit" }}
        />
      </View>
    </Label>
  );
}

// ---------- segmented control ----------

export function Segmented<V extends string>({ value, options, onChange, small }: {
  value: V; options: { value: V; label: string; dot?: boolean }[]; onChange: (v: V) => void; small?: boolean;
}) {
  const c = useColors();
  const [box, setBox] = useState<Record<string, { x: number; w: number }>>({});
  const x = useRef(new Animated.Value(0)).current;
  const w = useRef(new Animated.Value(0)).current;
  const placed = useRef(false);
  useEffect(() => {
    const l = box[value];
    if (!l) return;
    if (!placed.current) {
      x.setValue(l.x);
      w.setValue(l.w);
      placed.current = true;
      return;
    }
    Animated.parallel([
      Animated.spring(x, { toValue: l.x, ...motion.spring.enter, useNativeDriver: false }),
      Animated.spring(w, { toValue: l.w, ...motion.spring.enter, useNativeDriver: false }),
    ]).start();
  }, [box, value, x, w]);
  const h = small ? 28 : 34;
  return (
    <View style={{ flexDirection: "row", padding: 3, borderRadius: radii.pill, backgroundColor: c.surfaceAlt, borderWidth: 1, borderColor: c.hairline, alignSelf: "stretch" }}>
      <Animated.View style={{ position: "absolute", top: 3, left: 0, height: h, borderRadius: radii.pill, backgroundColor: c.anchorSoft, transform: [{ translateX: x }], width: w }} />
      {options.map((o) => (
        <Pressable
          key={o.value}
          accessibilityRole="tab"
          accessibilityState={{ selected: o.value === value }}
          onPress={() => onChange(o.value)}
          onLayout={(e) => {
            const { x: lx, width } = e.nativeEvent.layout;
            setBox((b) => (b[o.value]?.x === lx && b[o.value]?.w === width ? b : { ...b, [o.value]: { x: lx, w: width } }));
          }}
          style={web({ flex: 1, height: h, flexDirection: "row", gap: 6, alignItems: "center", justifyContent: "center", paddingHorizontal: 14, cursor: "pointer" })}
        >
          <Text style={[typography.callout, { fontSize: 13, fontWeight: o.value === value ? "700" : "500", color: o.value === value ? c.anchor : c.inkSecondary }]}>{o.label}</Text>
          {o.dot ? <Dot color={c.warning} /> : null}
        </Pressable>
      ))}
    </View>
  );
}

// ---------- popovers: menu and select ----------

export function Popover({ open, onClose, children, align = "left", minWidth }: { open: boolean; onClose: () => void; children: ReactNode; align?: "left" | "right"; minWidth?: number }) {
  const c = useColors();
  const { shadow } = useTheme();
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (!open) { v.setValue(0); return; }
    Animated.spring(v, { toValue: 1, ...motion.spring.enter, useNativeDriver: false }).start();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, v, onClose]);
  if (!open) return null;
  return (
    <>
      <Pressable accessibilityLabel="Close menu" onPress={onClose} style={web({ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, zIndex: 40, cursor: "default" })} />
      <Animated.View
        style={[
          web({ position: "absolute", top: "100%", marginTop: 6, zIndex: 50, minWidth: minWidth ?? 200, padding: 4, borderRadius: radii.md, backgroundColor: c.surface, ...shadow("lg") }),
          align === "right" ? { right: 0 } : { left: 0 },
          { opacity: v, transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [-6, 0] }) }, { scale: v.interpolate({ inputRange: [0, 1], outputRange: [0.97, 1] }) }] },
        ]}
      >
        {children}
      </Animated.View>
    </>
  );
}

function MenuRow({ label, onPress, selected }: { label: string; onPress: () => void; selected?: boolean }) {
  const c = useColors();
  return (
    <Pressable
      accessibilityRole="menuitem"
      onPress={onPress}
      style={({ hovered }) => web({ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 9, paddingHorizontal: 12, borderRadius: radii.xs, backgroundColor: selected ? c.anchorSoft : hovered ? c.surfaceHover : "transparent", cursor: "pointer" })}
    >
      <T v="footnote" c={selected ? "anchor" : "ink"} style={{ flex: 1, fontWeight: selected ? "700" : "500" }}>{label}</T>
      {selected ? <Icon name="check" size={15} color={c.anchor} /> : null}
    </Pressable>
  );
}

export function Menu({ label, items }: { label: string; items: ({ label: string; onPress: () => void } | "divider")[] }) {
  const c = useColors();
  const [open, setOpen] = useState(false);
  return (
    <View style={{ zIndex: open ? 60 : 1 }}>
      <Button label={label} icon={open ? "up" : "down"} iconRight onPress={() => setOpen(!open)} />
      <Popover open={open} onClose={() => setOpen(false)} align="right" minWidth={230}>
        {items.map((it, i) =>
          it === "divider" ? <View key={i} style={{ height: 1, backgroundColor: c.hairline, marginVertical: 4, marginHorizontal: 6 }} /> : (
            <MenuRow key={i} label={it.label} onPress={() => { setOpen(false); it.onPress(); }} />
          ),
        )}
      </Popover>
    </View>
  );
}

export function Select({ value, options, onChange, label, width }: { value: string; options: { value: string; label: string }[]; onChange: (v: string) => void; label: string; width?: number }) {
  const c = useColors();
  const [open, setOpen] = useState(false);
  const current = options.find((o) => o.value === value) ?? options[0];
  return (
    <View style={{ zIndex: open ? 60 : 1, width }}>
      <Pressable
        accessibilityRole="button" accessibilityLabel={label} onPress={() => setOpen(!open)}
        style={({ hovered }) => web({ height: 40, flexDirection: "row", alignItems: "center", gap: 8, paddingLeft: 12, paddingRight: 10, borderRadius: radii.sm, borderWidth: 1, borderColor: open ? c.anchor : c.hairline, backgroundColor: hovered ? c.surfaceHover : c.surfaceAlt, cursor: "pointer" })}
      >
        <T v="callout" style={{ flex: 1 }} numberOfLines={1}>{current?.label}</T>
        <Icon name={open ? "up" : "down"} size={15} color={c.inkTertiary} />
      </Pressable>
      <Popover open={open} onClose={() => setOpen(false)} minWidth={width ?? 220}>
        {options.map((o) => (
          <MenuRow key={o.value} label={o.label} selected={o.value === value} onPress={() => { setOpen(false); onChange(o.value); }} />
        ))}
      </Popover>
    </View>
  );
}

/** Decision-style choice: a row of pill radios. */
export function Choices({ value, options, onChange }: { value: string; options: { value: string; label: string }[]; onChange: (v: string) => void }) {
  const c = useColors();
  return (
    <View style={{ flexDirection: "row", flexWrap: "wrap", gap: 8 }}>
      {options.map((o) => {
        const on = o.value === value;
        return (
          <Pressable
            key={o.value} accessibilityRole="radio" accessibilityState={{ checked: on }} onPress={() => onChange(o.value)}
            style={({ hovered }) => web({ flexDirection: "row", alignItems: "center", gap: 8, height: 38, paddingHorizontal: 14, borderRadius: radii.sm, borderWidth: 1, borderColor: on ? c.anchor : c.hairline, backgroundColor: on ? c.anchorSoft : hovered ? c.surfaceHover : c.surfaceAlt, cursor: "pointer", transitionProperty: "background-color, border-color", transitionDuration: "150ms" })}
          >
            <View style={{ width: 16, height: 16, borderRadius: 8, borderWidth: 2, borderColor: on ? c.anchor : c.hairlineStrong, alignItems: "center", justifyContent: "center" }}>
              {on ? <View style={{ width: 8, height: 8, borderRadius: 4, backgroundColor: c.anchor }} /> : null}
            </View>
            <T v="footnote" style={{ fontWeight: "600" }}>{o.label}</T>
          </Pressable>
        );
      })}
    </View>
  );
}

/** Collapsible section with a spring-rotated chevron. */
export function Disclosure({ title, children, initiallyOpen }: { title: string; children: ReactNode; initiallyOpen?: boolean }) {
  const c = useColors();
  const [open, setOpen] = useState(!!initiallyOpen);
  return (
    <View>
      <Pressable accessibilityRole="button" accessibilityState={{ expanded: open }} onPress={() => setOpen(!open)} style={web({ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 6, cursor: "pointer" })}>
        <Icon name={open ? "down" : "right"} size={15} color={c.inkTertiary} />
        <T v="footnote" c="anchor" style={{ fontWeight: "600" }}>{title}</T>
      </Pressable>
      {open ? <Reveal y={-4}>{children}</Reveal> : null}
    </View>
  );
}

/** A plain file picker that opens the browser's dialog. */
export function FilePicker({ onFiles, accept, multiple = true, children }: { onFiles: (f: File[]) => void; accept: string; multiple?: boolean; children: (open: () => void) => ReactNode }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <>
      <input
        ref={ref} type="file" accept={accept} multiple={multiple} hidden
        onChange={(e) => { onFiles([...(e.target.files ?? [])]); e.target.value = ""; }}
      />
      {children(() => ref.current?.click())}
    </>
  );
}
