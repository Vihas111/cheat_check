import { View, useWindowDimensions } from "react-native";

import { useGet } from "../api/client";
import type { Compare, Panel } from "../api/types";
import { useRouter } from "../router";
import { radii, spacing, useColors } from "../theme";
import { AppBar, Loading, Page } from "../ui/chrome";
import { IgnoreText } from "../ui/IgnoreText";
import { Card, Disclosure, LinkText, Reveal, T, Tappable } from "../ui/primitives";

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function PanelCard({ p, assignment }: { p: Panel; assignment: string }) {
  const c = useColors();
  const { navigate } = useRouter();
  return (
    <Card style={{ flex: 1, minWidth: 300, gap: spacing.sm }}>
      <LinkText v="title3" onPress={() => navigate(`/s/${p.submission_id}`)}>{p.filename}</LinkText>
      <T v="footnote" c="inkSecondary">{cap(p.label)}</T>
      {p.thumb ? <a href={p.thumb} target="_blank" rel="noreferrer"><img src={p.thumb} alt={`${p.label} of ${p.filename}`} style={{ maxWidth: "100%", borderRadius: 4, border: `1px solid ${c.hairline}`, display: "block" }} /></a> : null}
      {p.chunks.length ? (
        <>
          <T v="overline" c="accent" style={{ marginTop: spacing.sm }}>{p.text_title}</T>
          <T v="mono" style={{ backgroundColor: c.surfaceAlt, padding: spacing.ms, borderRadius: radii.sm }}>
            {p.chunks.map(([text, hit], i) => (hit ? <T key={i} v="mono" style={{ backgroundColor: c.accentSoft, color: c.ink, fontWeight: "700" }}>{text + " "}</T> : text + " "))}
          </T>
          <IgnoreText itemId={p.item_id} lines={p.lines} assignment={assignment} />
        </>
      ) : null}
    </Card>
  );
}

export function CompareScreen({ mid }: { mid: string }) {
  const c = useColors();
  const { navigate } = useRouter();
  const { width } = useWindowDimensions();
  const { data, error, reload } = useGet<Compare>(`/m/${mid}`);

  if (!data) return <Page bar={<AppBar title="Compare" crumbs={[{ label: "Assignments", to: "/" }]} />}><Loading error={error} retry={reload} /></Page>;

  const bar = (
    <AppBar
      title={`Compare with ${data.b.filename}`} subtitle={`${cap(data.a.label)} and ${data.b.label}`}
      crumbs={[{ label: "Assignments", to: "/" }, { label: data.assignment.name, to: `/a/${data.assignment.id}` }, { label: data.a.filename, to: `/s/${data.a.submission_id}?tab=integrity` }]}
    />
  );

  return (
    <Page bar={bar}>
      <Reveal style={{ gap: spacing.sm }}>
        <T>{data.summary}</T>
        <T v="footnote" c="inkSecondary">Look for an innocent explanation too: given material, a shared data set, or a result every correct answer produces.</T>
      </Reveal>

      {data.siblings.length > 1 ? (
        <View style={{ flexDirection: "row", alignItems: "center", flexWrap: "wrap", gap: 6 }}>
          <T v="footnote" c="inkSecondary">Matches between these two files:</T>
          {data.siblings.map((id, i) => {
            const on = id === data.id;
            return (
              <Tappable key={id} href={`/m/${id}`} onPress={() => navigate(`/m/${id}`)} label={`Match ${i + 1}`} style={{ minWidth: 34, height: 34, borderRadius: radii.sm, backgroundColor: on ? c.anchorSurface : c.surfaceAlt, alignItems: "center", justifyContent: "center" }}>
                <T v="footnote" style={{ color: on ? c.onAnchor : c.ink, fontWeight: "600" }}>{i + 1}</T>
              </Tappable>
            );
          })}
        </View>
      ) : null}

      <Reveal delay={60}>
        <View style={{ flexDirection: width >= 760 ? "row" : "column", gap: spacing.md, alignItems: "flex-start" }}>
          <PanelCard p={data.a} assignment={data.assignment.name} />
          <PanelCard p={data.b} assignment={data.assignment.name} />
        </View>
      </Reveal>

      {data.overlay ? (
        <Card pad={spacing.md}>
          <Disclosure title="Show matching feature points">
            <View style={{ gap: spacing.sm, paddingVertical: 8 }}>
              <T v="footnote" c="inkSecondary">Lines join points found in both images. Many parallel lines mean the same picture.</T>
              <img src={data.overlay} alt="Matching feature points between the two images" loading="lazy" style={{ maxWidth: "100%" }} />
            </View>
          </Disclosure>
        </Card>
      ) : null}
    </Page>
  );
}
