import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { Pressable, View } from "react-native";

import { useRouter } from "../router";
import { layout, radii, spacing, useColors, useTheme } from "../theme";
import { Button, Card, Icon, IconButton, LinkText, Reveal, T, web } from "./primitives";

// ---------- app bar ----------

function ThemeToggle() {
  const { preference, setPreference } = useTheme();
  const c = useColors();
  const next = { system: "light", light: "dark", dark: "system" } as const;
  const icon = { system: "system", light: "sun", dark: "moon" }[preference];
  return <IconButton icon={icon} label={`Theme: ${preference}. Click to change.`} onPress={() => setPreference(next[preference])} />;
}

export type Crumb = { label: string; to: string };

export function AppBar({ title, subtitle, crumbs = [], actions, compact }: {
  title: string; subtitle?: string; crumbs?: Crumb[]; actions?: ReactNode; compact?: boolean;
}) {
  const c = useColors();
  const { navigate } = useRouter();
  const last = crumbs.length - 1;
  return (
    <View style={web({ position: "sticky", top: 0, zIndex: 30, backgroundColor: c.surfaceOverlay, borderBottomWidth: 1, borderBottomColor: c.hairline, backdropFilter: "saturate(180%) blur(16px)" })}>
      <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.lg, paddingVertical: compact ? 8 : 12, minHeight: layout.barHeight }}>
        <View style={{ flex: 1, minWidth: 200 }}>
          {crumbs.length ? (
            <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap" }}>
              {crumbs.map((cr, i) => (
                <View key={cr.to} style={{ flexDirection: "row", alignItems: "center" }}>
                  {i === last ? <Icon name="left" size={14} color={c.anchor} /> : null}
                  <LinkText v="footnote" onPress={() => navigate(cr.to)} style={i === last ? { fontWeight: "600" } : undefined}>{cr.label}</LinkText>
                  {i < last ? <View style={{ marginHorizontal: 4 }}><Icon name="right" size={12} color={c.inkTertiary} /></View> : null}
                </View>
              ))}
            </View>
          ) : null}
          <T v={compact ? "title2" : "title1"} numberOfLines={1}>{title}</T>
          {subtitle ? <T v="footnote" c="inkSecondary" numberOfLines={1}>{subtitle}</T> : null}
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" }}>
          {actions}
          <ThemeToggle />
        </View>
      </View>
    </View>
  );
}

export function Page({ bar, children, narrow, footer = true }: { bar: ReactNode; children: ReactNode; narrow?: boolean; footer?: boolean }) {
  return (
    <View style={web({ minHeight: "100vh" })}>
      {bar}
      <View style={{ flex: 1, width: "100%", maxWidth: narrow ? layout.formMaxWidth : layout.contentMaxWidth, alignSelf: "center", padding: spacing.lg, gap: spacing.md }}>
        {children}
      </View>
      {footer ? (
        <View style={{ width: "100%", maxWidth: layout.contentMaxWidth, alignSelf: "center", paddingHorizontal: spacing.lg, paddingBottom: spacing.xl }}>
          <T v="caption" c="inkTertiary">Grades are entered and released only by you. Integrity flags are suggestions that wait for your decision. Files and results stay on this computer.</T>
        </View>
      ) : null}
    </View>
  );
}

/** Shown while a screen's first load is in flight, and when it fails. */
export function Loading({ error, retry }: { error?: string; retry?: () => void }) {
  return (
    <View style={{ padding: spacing.xxl, alignItems: "center", gap: spacing.md }}>
      {error ? (
        <>
          <T c="negative">{error}</T>
          {retry ? <Button label="Try again" onPress={retry} /> : null}
        </>
      ) : <T c="inkTertiary">Loading…</T>}
    </View>
  );
}

// ---------- toast and confirm ----------

type Toast = { id: number; text: string; tone: "info" | "error"; action?: { label: string; onPress: () => void } };
type Feedback = {
  toast: (text: string, opts?: { tone?: "info" | "error"; action?: Toast["action"] }) => void;
  confirm: (text: string, opts?: { confirmLabel?: string; danger?: boolean }) => Promise<boolean>;
};
const FeedbackContext = createContext<Feedback>(null as unknown as Feedback);
export const useFeedback = () => useContext(FeedbackContext);

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const c = useColors();
  const { shadow } = useTheme();
  const [toast, setToast] = useState<Toast | null>(null);
  const [ask, setAsk] = useState<{ text: string; confirmLabel: string; danger: boolean; done: (ok: boolean) => void } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const show = useCallback<Feedback["toast"]>((text, opts) => {
    const t: Toast = { id: Date.now(), text, tone: opts?.tone ?? "info", action: opts?.action };
    setToast(t);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setToast((cur) => (cur?.id === t.id ? null : cur)), t.tone === "error" || t.action ? 8000 : 4500);
  }, []);

  const confirm = useCallback<Feedback["confirm"]>(
    (text, opts) => new Promise((done) => setAsk({ text, confirmLabel: opts?.confirmLabel ?? "Continue", danger: !!opts?.danger, done })),
    [],
  );

  const answer = (ok: boolean) => { ask?.done(ok); setAsk(null); };

  return (
    <FeedbackContext.Provider value={{ toast: show, confirm }}>
      {children}
      {toast ? (
        <View pointerEvents="box-none" style={web({ position: "fixed", left: 0, right: 0, bottom: 24, zIndex: 100, alignItems: "center", paddingHorizontal: 16 })}>
          <Reveal key={toast.id} y={16}>
            <View accessibilityRole="alert" style={[{ flexDirection: "row", alignItems: "center", gap: 14, maxWidth: 560, paddingVertical: 12, paddingLeft: 18, paddingRight: 12, borderRadius: radii.md, backgroundColor: toast.tone === "error" ? c.negative : c.ink }, web(shadow("lg"))]}>
              <T v="callout" style={{ color: toast.tone === "error" ? "#fff" : c.canvas, flexShrink: 1 }}>{toast.text}</T>
              {toast.action ? <Button small variant="plain" label={toast.action.label} onPress={() => { toast.action?.onPress(); setToast(null); }} style={{ backgroundColor: c.surface, borderRadius: radii.pill }} /> : null}
              <IconButton size={28} icon="close" label="Dismiss" onPress={() => setToast(null)} />
            </View>
          </Reveal>
        </View>
      ) : null}
      {ask ? (
        <View style={web({ position: "fixed", top: 0, left: 0, right: 0, bottom: 0, zIndex: 120, alignItems: "center", justifyContent: "center", padding: 16 })}>
          <Pressable accessibilityLabel="Cancel" onPress={() => answer(false)} style={web({ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, backgroundColor: c.scrim })} />
          <Reveal y={12} style={{ width: "100%", maxWidth: 440 }}>
            <Card elevation="lg" style={{ gap: spacing.md }}>
              <T v="body">{ask.text}</T>
              <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: spacing.sm }}>
                <Button variant="plain" label="Cancel" onPress={() => answer(false)} />
                <Button variant={ask.danger ? "danger" : "primary"} label={ask.confirmLabel} onPress={() => answer(true)} />
              </View>
            </Card>
          </Reveal>
        </View>
      ) : null}
    </FeedbackContext.Provider>
  );
}

// ---------- uploads ----------

/** True while files are dragged over the window; calls onFiles when they are dropped. */
export function useWindowDrop(onFiles: (f: File[]) => void) {
  const [over, setOver] = useState(false);
  const cb = useRef(onFiles);
  cb.current = onFiles;
  useEffect(() => {
    let depth = 0;
    const has = (e: DragEvent) => !!e.dataTransfer?.types.includes("Files");
    const enter = (e: DragEvent) => { if (has(e)) { e.preventDefault(); depth++; setOver(true); } };
    const overFn = (e: DragEvent) => { if (has(e)) e.preventDefault(); };
    const leave = (e: DragEvent) => { if (has(e) && --depth <= 0) { depth = 0; setOver(false); } };
    const drop = (e: DragEvent) => { if (has(e)) { e.preventDefault(); depth = 0; setOver(false); cb.current([...(e.dataTransfer?.files ?? [])]); } };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragover", overFn);
    window.addEventListener("dragleave", leave);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragover", overFn);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("drop", drop);
    };
  }, []);
  return over;
}
