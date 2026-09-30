import { View } from "react-native";

import { useGet } from "../api/client";
import type { Calibration, Chart, Groups } from "../api/types";
import { useMeta } from "../meta";
import { useRouter } from "../router";
import { spacing, useColors } from "../theme";
import { AppBar, Loading, Page } from "../ui/chrome";
import { Card, Empty, LinkText, Reveal, T, Tier, web } from "../ui/primitives";

function Cell({ children, flex = 1, head, right }: { children?: React.ReactNode; flex?: number; head?: boolean; right?: boolean }) {
  return <View style={{ flex, minWidth: 0 }}><T v="footnote" c={head ? "inkSecondary" : "ink"} style={{ fontWeight: head ? "400" : "500", textAlign: right ? "right" : "left" }}>{children}</T></View>;
}

export function GroupsScreen({ aid }: { aid: string }) {
  const c = useColors();
  const { navigate } = useRouter();
  const meta = useMeta();
  const { data, error, reload } = useGet<Groups>(`/a/${aid}/clusters`);
  const crumbs = (name?: string) => [{ label: "Assignments", to: "/" }, { label: name ?? "Assignment", to: `/a/${aid}` }];
  if (!data) return <Page bar={<AppBar title="Similar groups" crumbs={crumbs()} />}><Loading error={error} retry={reload} /></Page>;

  return (
    <Page bar={<AppBar title="Similar groups" crumbs={crumbs(data.assignment.name)} />}>
      <T v="footnote" c="inkSecondary">Submissions linked by distinctive shared content. A link is a suggestion to compare them, not a finding. Content most students share never links anyone.</T>
      {data.groups.length ? data.groups.map((g, gi) => (
        <Reveal key={gi} delay={gi * 50}>
          <Card style={{ gap: spacing.sm }}>
            <T v="title3">{g.members.length} linked submissions</T>
            <View style={{ flexDirection: "row", gap: spacing.md, paddingVertical: 4, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
              <Cell head flex={2}>Submission</Cell><Cell head flex={1.5}>App suggests</Cell><Cell head flex={2}> </Cell>
            </View>
            {g.members.map((m) => (
              <View key={m.id} style={{ flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: 4 }}>
                <View style={{ flex: 2 }}><LinkText v="footnote" onPress={() => navigate(`/s/${m.id}?tab=integrity`)}>{m.filename}</LinkText></View>
                <View style={{ flex: 1.5 }}>{m.tier ? <Tier tier={m.tier} label={meta.tier[m.tier] ?? m.tier} /> : null}</View>
                <View style={{ flex: 2 }}>{m.id === g.hub ? <T v="caption" c="inkSecondary" style={{ fontWeight: "400" }}>shares the most with the others</T> : null}</View>
              </View>
            ))}
            <T v="overline" c="accent">Links</T>
            <View style={{ flexDirection: "row", gap: spacing.md, paddingVertical: 4, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
              <Cell head flex={3}>Between</Cell><Cell head>Shared items</Cell><Cell head>Strength</Cell>
            </View>
            {g.edges.map((e, i) => (
              <View key={i} style={{ flexDirection: "row", gap: spacing.md, paddingVertical: 4 }}>
                <Cell flex={3}>{e.a} and {e.b}</Cell><Cell>{e.items}</Cell><Cell>{e.weight}</Cell>
              </View>
            ))}
          </Card>
        </Reveal>
      )) : <Card><Empty>No groups. No two submissions share distinctive content.</Empty></Card>}
    </Page>
  );
}

function Histogram({ chart }: { chart: Chart }) {
  const c = useColors();
  const { hist, current, cut, fmt, setting } = chart;
  const span = hist.length, lo = hist[0]?.lo ?? 0, step = span > 1 ? hist[1].lo - hist[0].lo : 1;
  const at = (v: number) => `${Math.max(0, Math.min(1, (v - lo) / (step * span))) * 100}%`;
  return (
    <Card style={{ flex: 1, minWidth: 300, gap: spacing.sm }}>
      <T v="title3">{chart.title}</T>
      <View accessibilityRole="image" accessibilityLabel={`${chart.title} histogram`} style={{ height: 140, flexDirection: "row", alignItems: "flex-end", gap: 2, borderBottomWidth: 1, borderBottomColor: c.hairlineStrong, marginTop: spacing.sm }}>
        {hist.map((b, i) => (
          <View key={i} style={web({ flex: 1, height: "100%", justifyContent: "flex-end" })}>
            <View style={{ height: `${Math.max(b.h * 100, b.n ? 2 : 0.7)}%`, backgroundColor: c.hairlineStrong, borderTopLeftRadius: 2, borderTopRightRadius: 2 }} />
          </View>
        ))}
        <View style={{ position: "absolute", top: -4, bottom: 0, left: at(current) as never, borderLeftWidth: 2, borderLeftColor: c.anchor }} />
        {cut !== null ? <View style={{ position: "absolute", top: -4, bottom: 0, left: at(cut) as never, borderLeftWidth: 2, borderLeftColor: c.warning, borderStyle: "dashed" }} /> : null}
      </View>
      <T v="footnote" c="inkSecondary"><T v="mono" style={{ backgroundColor: c.surfaceAlt }}>{setting}</T> is {current}{cut !== null ? `; suggested ${cut}` : ""}.{fmt === "pct" ? "" : ""}</T>
    </Card>
  );
}

export function CalibrateScreen({ aid }: { aid: string }) {
  const c = useColors();
  const { data, error, reload } = useGet<Calibration>(`/a/${aid}/calibrate`);
  const crumbs = (name?: string) => [{ label: "Assignments", to: "/" }, { label: name ?? "Assignment", to: `/a/${aid}` }];
  if (!data) return <Page bar={<AppBar title="Calibrate the similarity check" crumbs={crumbs()} />}><Loading error={error} retry={reload} /></Page>;

  return (
    <Page bar={<AppBar title="Calibrate the similarity check" crumbs={crumbs(data.assignment.name)} />}>
      <T v="footnote" c="inkSecondary" style={{ maxWidth: 680 }}>
        How {data.n} read submissions are spread. Honest work usually bunches on the left, and copies stand apart on the right. If the current setting cuts through the bunch, too many honest submissions get flagged. Change values in Settings, then re-scan.
      </T>
      <View style={{ flexDirection: "row", gap: spacing.md }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}><View style={{ width: 14, borderTopWidth: 2, borderTopColor: c.anchor }} /><T v="footnote" c="inkSecondary">current setting</T></View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}><View style={{ width: 14, borderTopWidth: 2, borderTopColor: c.warning, borderStyle: "dashed" }} /><T v="footnote" c="inkSecondary">suggested cut-off</T></View>
      </View>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
        {data.charts.map((ch, i) => <Reveal key={ch.setting} delay={i * 50} style={{ flex: 1, minWidth: 300 }}><Histogram chart={ch} /></Reveal>)}
      </View>
    </Page>
  );
}
