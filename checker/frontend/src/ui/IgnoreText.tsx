import { useState } from "react";
import { View } from "react-native";

import { api } from "../api/client";
import { radii, spacing, useColors } from "../theme";
import { useFeedback } from "./chrome";
import { Button, LinkText, T, Tappable } from "./primitives";

/** Pick lines of an item's text (for example the question, not the answer) and ignore just those. */
export function IgnoreText({ itemId, lines, assignment, onDone }: { itemId: number; lines: string[]; assignment: string; onDone?: () => void }) {
  const c = useColors();
  const { toast, confirm } = useFeedback();
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [busy, setBusy] = useState(false);
  if (!lines.length) return null;

  if (!open) return <LinkText v="caption" onPress={() => setOpen(true)} style={{ marginTop: 4 }}>Ignore part of the text, such as the question…</LinkText>;

  const toggle = (i: number) => setPicked((p) => { const n = new Set(p); if (!n.delete(i)) n.add(i); return n; });
  const close = () => { setOpen(false); setPicked(new Set()); };
  const submit = async () => {
    if (!(await confirm(`Ignore the ${picked.size} selected ${picked.size === 1 ? "line" : "lines"} in every ${assignment} submission? The rest of this item still counts. Everything will be re-scanned.`, { confirmLabel: "Ignore these lines" }))) return;
    setBusy(true);
    try {
      await api.post(`/item/${itemId}/ignore-text`, { lines: [...picked] });
      toast("Ignored. Re-scanning the assignment.");
      close();
      onDone?.();
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
    }
    setBusy(false);
  };

  return (
    <View style={{ gap: 6, marginTop: 4 }}>
      <T v="footnote" c="inkSecondary">Tick the lines to ignore, for example the question. The answer stays checked.</T>
      <View style={{ borderWidth: 1, borderColor: c.hairline, borderRadius: radii.sm, overflow: "hidden", maxHeight: 280 } as never}>
        <View style={{ maxHeight: 280, overflow: "scroll" } as never}>
          {lines.map((ln, i) => {
            const on = picked.has(i);
            return (
              <Tappable key={i} onPress={() => toggle(i)} label={`${on ? "Unselect" : "Select"} line: ${ln}`} style={{ backgroundColor: on ? c.anchorSoft : "transparent" }}>
                <View style={{ flexDirection: "row", gap: 8, paddingVertical: 4, paddingHorizontal: 8, alignItems: "flex-start" }}>
                  <T v="mono" c={on ? "anchor" : "inkTertiary"}>{on ? "☑" : "☐"}</T>
                  <T v="mono" style={{ flex: 1, fontSize: 12 }}>{ln}</T>
                </View>
              </Tappable>
            );
          })}
        </View>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        <Button small variant="primary" label={picked.size ? `Ignore ${picked.size} ${picked.size === 1 ? "line" : "lines"}` : "Ignore selected lines"} disabled={!picked.size} loading={busy} onPress={submit} />
        <Button small label="Select all" onPress={() => setPicked(new Set(lines.map((_, i) => i)))} />
        <Button small variant="plain" label="Cancel" onPress={close} />
      </View>
    </View>
  );
}
