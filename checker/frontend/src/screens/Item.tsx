import { View } from "react-native";

import { api, useGet } from "../api/client";
import type { ItemMatch, ItemPage } from "../api/types";
import { useRouter } from "../router";
import { radii, spacing, useColors } from "../theme";
import { AppBar, Loading, Page, useFeedback } from "../ui/chrome";
import { IgnoreRegion, MaskedThumb } from "../ui/IgnoreRegion";
import { IgnoreText } from "../ui/IgnoreText";
import { useDismiss } from "../ui/useDismiss";
import { Button, Card, Pill, Reveal, T, web } from "../ui/primitives";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const KIND_WHY: Record<string, string> = {
  image_hash: "The pictures look the same. Their fingerprints (a short summary of how a picture looks) are almost identical, and mirrored, rotated or colour-inverted copies are checked too.",
  image_feature: "Many distinctive points line up between the pictures, so one is a crop, resize or re-export of the other.",
  ocr_text: "The text read from the image, or the typed text, contains the same runs of words.",
  code_structure: "The code has the same structure once variable names and spacing are ignored.",
};

function Preview({ thumb, lines, label, masks }: { thumb: string | null; lines: string[]; label: string; masks?: number[][] }) {
  const c = useColors();
  if (thumb) return <a href={thumb} target="_blank" rel="noreferrer"><MaskedThumb src={thumb} alt={label} masks={masks} style={{ maxHeight: 220, margin: "0 auto", borderRadius: 4, border: `1px solid ${c.hairline}` }} /></a>;
  return <T v="mono" style={{ backgroundColor: c.surfaceAlt, padding: 8, borderRadius: radii.xs, fontSize: 11 } as never}>{lines.join("\n")}</T>;
}

function FileLink({ id, name, sub }: { id: number; name: string; sub?: string }) {
  const { navigate } = useRouter();
  const c = useColors();
  return (
    <View>
      <a href={`/s/${id}`} onClick={(e) => { if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); navigate(`/s/${id}`); } }}
        style={{ color: c.anchor, fontWeight: 600, fontSize: 15, textDecoration: "none", wordBreak: "break-all" }}>{name}</a>
      {sub ? <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }}>{sub}</T> : null}
    </View>
  );
}

function MatchCard({ m, onChanged }: { m: ItemMatch; onChanged: () => void }) {
  const c = useColors();
  const { navigate } = useRouter();
  const dismiss = useDismiss();
  return (
    <Card style={{ flexGrow: 1, flexBasis: 280, maxWidth: "100%", gap: spacing.sm }} pad={spacing.md}>
      <FileLink id={m.submission_id} name={m.filename} sub={[m.student?.name, m.student?.student_id].filter(Boolean).join(" · ") || undefined} />
      <View style={{ flexDirection: "row", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        <Pill label={m.what} tone="warning" />
        <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }}>{cap(m.label)}</T>
      </View>
      <Preview thumb={m.thumb} lines={m.lines} label={m.label} masks={m.masks} />
      <T v="footnote">{m.why}</T>
      {m.shared.length ? (
        <View style={{ gap: 4 }}>
          <T v="caption" c="inkSecondary">Shared wording</T>
          {m.shared.map((s, i) => <T key={i} v="mono" style={{ backgroundColor: c.accentSoft, padding: 6, borderRadius: radii.xs, fontSize: 11 } as never}>{s}</T>)}
        </View>
      ) : null}
      <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
        <Button small variant="danger" label="Not a match" title="These two are not really the same. Stop counting this pair." onPress={() => dismiss(m.match_id, onChanged)} />
        <a href={`/m/${m.match_id}`} onClick={(e) => { if (e.button === 0 && !e.metaKey && !e.ctrlKey && !e.shiftKey) { e.preventDefault(); navigate(`/m/${m.match_id}`); } }} style={{ textDecoration: "none" }}>
          <Button small label="Compare side by side" onPress={() => navigate(`/m/${m.match_id}`)} />
        </a>
      </View>
    </Card>
  );
}

export function ItemScreen({ iid }: { iid: string }) {
  const c = useColors();
  const { navigate } = useRouter();
  const { toast, confirm } = useFeedback();
  const { data, error, reload } = useGet<ItemPage>(`/i/${iid}`);

  if (!data) return <Page bar={<AppBar title="Shared item" crumbs={[{ label: "Assignments", to: "/" }]} />}><Loading error={error} retry={reload} /></Page>;

  const { item, submission, assignment, matches } = data;
  const files = new Set(matches.map((m) => m.submission_id)).size;
  const bar = (
    <AppBar
      title={`${cap(item.label)} of ${submission.filename}`}
      subtitle={matches.length ? `Also found in ${files} other ${files === 1 ? "submission" : "submissions"}` : "Not found in any other submission"}
      crumbs={[{ label: "Assignments", to: "/" }, { label: assignment.name, to: `/a/${assignment.id}` }, { label: submission.filename, to: `/s/${submission.id}?tab=integrity` }]}
    />
  );
  const ignore = async () => {
    if (!(await confirm(`Ignore this content in every ${assignment.name} submission, for example because it is given material? Everything will be re-scanned.`, { confirmLabel: "Ignore everywhere" }))) return;
    await api.post(`/item/${item.id}/ignore`);
    toast("Ignored. Re-scanning the assignment.");
    navigate(`/s/${submission.id}?tab=integrity`);
  };

  return (
    <Page bar={bar}>
      <Reveal style={{ gap: spacing.sm }}>
        <T>
          {matches.length
            ? `${files} other ${files === 1 ? "submission has" : "submissions have"} this ${item.label}. ${item.df ? `In total ${item.df} files contain it` : ""}${item.weight != null ? `, so it counts with weight ${item.weight.toFixed(2)} (0 means so many students have it that it proves nothing).` : "."}`
            : "No other submission shares this content."}
        </T>
        {item.kinds.length ? (
          <View style={{ gap: 2 }}>
            <T v="overline" c="accent">Why they match</T>
            {item.kinds.map((k) => <T key={k} v="footnote" c="inkSecondary">{KIND_WHY[k] ?? k}</T>)}
            <T v="footnote" c="inkSecondary">Look for an innocent explanation too: given material, a shared data set, or a result every correct answer produces.</T>
          </View>
        ) : null}
      </Reveal>

      <Reveal delay={60}>
        <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md, alignItems: "flex-start" }}>
          <Card style={{ flexGrow: 1, flexBasis: 280, maxWidth: "100%", gap: spacing.sm, borderColor: c.warningBorder }} pad={spacing.md}>
            <T v="overline" c="accent">This item</T>
            <FileLink id={submission.id} name={submission.filename} sub={[submission.student?.name, submission.student?.student_id].filter(Boolean).join(" · ") || undefined} />
            <Preview thumb={item.thumb} lines={item.lines.slice(0, 12)} label={item.label} masks={item.masks} />
            {matches.length ? (
              <View style={{ gap: 2 }}>
                <T v="caption" c="anchor" onPress={ignore} style={web({ cursor: "pointer" })}>Ignore everywhere, it is given material</T>
                <IgnoreText itemId={item.id} lines={item.lines} assignment={assignment.name} onDone={() => navigate(`/s/${submission.id}?tab=integrity`)} />
                <IgnoreRegion itemId={item.id} thumb={item.thumb} masks={item.masks} assignment={assignment.name} onDone={() => navigate(`/s/${submission.id}?tab=integrity`)} />
              </View>
            ) : null}
          </Card>
          {matches.map((m) => <MatchCard key={m.match_id} m={m} onChanged={reload} />)}
        </View>
      </Reveal>
    </Page>
  );
}
