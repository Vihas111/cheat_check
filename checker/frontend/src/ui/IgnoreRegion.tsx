import { useRef, useState, type CSSProperties, type PointerEvent as RPointerEvent } from "react";
import { View } from "react-native";

import { api } from "../api/client";
import { spacing, useColors } from "../theme";
import { useFeedback } from "./chrome";
import { Button, LinkText, T } from "./primitives";

type Box = [number, number, number, number];

/** An image with its ignored regions drawn as dashed boxes. */
export function MaskedThumb({ src, alt, masks, style }: { src: string; alt: string; masks?: number[][]; style?: CSSProperties }) {
  const c = useColors();
  return (
    <div style={{ position: "relative", display: "inline-block", maxWidth: "100%", lineHeight: 0 }}>
      <img src={src} alt={alt} loading="lazy" style={{ maxWidth: "100%", display: "block", ...style }} />
      {(masks ?? []).map((m, i) => (
        <div key={i} title="Ignored in the comparison" style={{ position: "absolute", left: `${m[0] * 100}%`, top: `${m[1] * 100}%`, width: `${(m[2] - m[0]) * 100}%`, height: `${(m[3] - m[1]) * 100}%`, border: `2px dashed ${c.inkTertiary}`, background: "rgba(127,127,127,0.35)", pointerEvents: "none", boxSizing: "border-box" }} />
      ))}
    </div>
  );
}

/** Draw a box over the part of an image to ignore (a question header, a tool bar), then ignore it everywhere. */
export function IgnoreRegion({ itemId, thumb, masks, assignment, onDone }: { itemId: number; thumb: string | null; masks?: number[][]; assignment: string; onDone?: () => void }) {
  const c = useColors();
  const { toast, confirm } = useFeedback();
  const [open, setOpen] = useState(false);
  const [box, setBox] = useState<Box | null>(null);
  const [busy, setBusy] = useState(false);
  const start = useRef<[number, number] | null>(null);
  const area = useRef<HTMLDivElement>(null);
  if (!thumb) return null;

  if (!open) return <LinkText v="caption" onPress={() => setOpen(true)} style={{ marginTop: 4 }}>Ignore part of the image…</LinkText>;

  const point = (e: RPointerEvent<HTMLDivElement>): [number, number] => {
    const r = area.current!.getBoundingClientRect();
    return [Math.min(Math.max((e.clientX - r.left) / r.width, 0), 1), Math.min(Math.max((e.clientY - r.top) / r.height, 0), 1)];
  };
  const down = (e: RPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    (e.currentTarget as HTMLDivElement).setPointerCapture(e.pointerId);
    start.current = point(e);
    setBox(null);
  };
  const move = (e: RPointerEvent<HTMLDivElement>) => {
    if (!start.current) return;
    const [x, y] = point(e), [sx, sy] = start.current;
    setBox([Math.min(sx, x), Math.min(sy, y), Math.max(sx, x), Math.max(sy, y)]);
  };
  const up = () => { start.current = null; };
  const close = () => { setOpen(false); setBox(null); };
  const tooSmall = !box || box[2] - box[0] < 0.01 || box[3] - box[1] < 0.01;

  const submit = async () => {
    if (!box || tooSmall) return;
    if (!(await confirm(`Ignore this part of the image in every ${assignment} submission? Wherever the same part appears, it is blanked out before images are compared, and text read from it is dropped. Everything will be re-scanned.`, { confirmLabel: "Ignore this part" }))) return;
    setBusy(true);
    try {
      await api.post(`/item/${itemId}/ignore-region`, { box });
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
      <T v="footnote" c="inkSecondary">Drag a box over the part to ignore. The rest of the image still counts. Grey dashed boxes are already ignored.</T>
      <div ref={area} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
        style={{ position: "relative", display: "inline-block", maxWidth: "100%", lineHeight: 0, cursor: "crosshair", touchAction: "none", userSelect: "none", border: `1px solid ${c.hairline}` }}>
        <img src={thumb} alt="Draw a box on this image" draggable={false} style={{ maxWidth: "100%", display: "block" }} />
        {(masks ?? []).map((m, i) => (
          <div key={i} style={{ position: "absolute", left: `${m[0] * 100}%`, top: `${m[1] * 100}%`, width: `${(m[2] - m[0]) * 100}%`, height: `${(m[3] - m[1]) * 100}%`, border: `2px dashed ${c.inkTertiary}`, background: "rgba(127,127,127,0.35)", pointerEvents: "none", boxSizing: "border-box" }} />
        ))}
        {box ? <div style={{ position: "absolute", left: `${box[0] * 100}%`, top: `${box[1] * 100}%`, width: `${(box[2] - box[0]) * 100}%`, height: `${(box[3] - box[1]) * 100}%`, border: `2px solid ${c.anchor}`, background: "rgba(40,100,220,0.22)", pointerEvents: "none", boxSizing: "border-box" }} /> : null}
      </div>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        <Button small variant="primary" label="Ignore this part everywhere" disabled={tooSmall} loading={busy} onPress={submit} />
        <Button small variant="plain" label="Cancel" onPress={close} />
      </View>
    </View>
  );
}
