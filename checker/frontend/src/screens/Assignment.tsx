import { useCallback, useEffect, useRef, useState } from "react";
import { TextInput, View, useWindowDimensions } from "react-native";

import { api, isBusy, useGet, useInterval, type RescanProgress, type Status } from "../api/client";
import type { Dashboard, Row } from "../api/types";
import { fmt, GRADE_LABEL, pct, useMeta, when } from "../meta";
import { useQuery, useRouter } from "../router";
import { radii, spacing, useColors } from "../theme";
import { AppBar, Loading, Page, useFeedback, useWindowDrop } from "../ui/chrome";
import {
  Button, Card, Disclosure, Dot, Empty, FilePicker, Icon, Menu, Pill, ProgressBar, Reveal, Select, T, Tappable, Tier, useFocusRing, web,
} from "../ui/primitives";
import { useUploader } from "../upload";

const WAITING: Record<string, string> = { queued: "Waiting to be read", processing: "Being read", failed: "Could not be read" };

function Stat({ label, value, of, note, warn, onPress, first }: { label: string; value: number; of?: number; note: string; warn?: boolean; onPress: () => void; first?: boolean }) {
  const c = useColors();
  return (
    <Tappable onPress={onPress} label={label} style={{ flexGrow: 1, flexBasis: 200, borderLeftWidth: first ? 0 : 1, borderLeftColor: c.hairline }}>
      <View style={{ padding: spacing.lg, gap: 2 }}>
        <T v="overline" c="accent">{label}</T>
        <T v="metric" c={warn ? "warning" : "ink"}>{value}{of !== undefined ? <T v="footnote" c="inkSecondary">  of {of}</T> : null}</T>
        {of !== undefined ? <View style={{ marginTop: 4 }}><ProgressBar value={of ? (value / of) * 100 : 0} /></View> : null}
        <T v="caption" c={warn ? "warning" : "inkTertiary"} style={{ fontWeight: "400", marginTop: of !== undefined ? 4 : 0 }}>{note}</T>
      </View>
    </Tappable>
  );
}

function eta(sec: number | null) {
  if (sec == null) return "";
  return sec < 60 ? `about ${Math.max(5, Math.round(sec / 5) * 5)} s left` : `about ${Math.round(sec / 60)} min left`;
}

/** What a re-scan is doing right now: the step, how far it is, the file it is on and a time estimate. */
function RescanStatus({ r }: { r?: RescanProgress | null }) {
  if (!r) return (
    <View style={{ gap: 4 }}>
      <ProgressBar value={3} />
      <T v="footnote" c="inkSecondary">Re-scanning: starting. Results will update when it finishes.</T>
    </View>
  );
  const frac = r.total ? r.done / r.total : 0;
  const overall = ((r.step - 1 + frac) / r.steps) * 100;
  const counts = r.total ? `${r.done} of ${r.total}` : "preparing";
  return (
    <View style={{ gap: 4 }}>
      <ProgressBar value={Math.max(overall, 3)} />
      <T v="footnote" c="inkSecondary">
        <T v="footnote" style={{ fontWeight: "700" }}>Re-scanning, step {r.step} of {r.steps}: {r.phase}</T>
        {` · ${counts}${r.total ? ` (${Math.round(frac * 100)}%)` : ""}`}{r.eta_s != null ? ` · ${eta(r.eta_s)}` : ""}
      </T>
      {r.file ? <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }} numberOfLines={1}>Now: {r.file}</T> : null}
      <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }}>It is safe to keep browsing. Flags and similarity update when this finishes.</T>
    </View>
  );
}

function GradePill({ row }: { row: Row }) {
  if (!row.gradable) return <Pill label={row.is_seed ? "Past cohort" : "Reference"} />;
  const s = row.mark?.status ?? "none";
  return <Pill label={(s === "released" ? "✓ " : "") + GRADE_LABEL[s]} tone={s === "released" ? "positive" : s === "draft" ? "anchor" : "neutral"} />;
}

function SubRow({ row, max, wide, index }: { row: Row; max: number; wide: boolean; index: number }) {
  const c = useColors();
  const { navigate } = useRouter();
  const meta = useMeta();
  const name = row.student?.name || row.filename;
  const sub = row.student?.name ? row.filename : row.student?.student_id ?? "";
  return (
    <Reveal delay={Math.min(index, 12) * 30} y={6}>
      <Tappable href={`/s/${row.id}`} onPress={() => navigate(`/s/${row.id}`)} label={name} style={{ borderTopWidth: 1, borderTopColor: c.hairline }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.md, paddingHorizontal: spacing.lg, paddingVertical: 12, minHeight: 60 }}>
          <View style={{ flex: 2.2, minWidth: 0 }}>
            <T v="bodyStrong" numberOfLines={1}>{name}</T>
            {sub ? <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }} numberOfLines={1}>{sub}</T> : null}
          </View>
          {wide ? (
            <View style={{ flex: 0.7, alignItems: "flex-end" }}>
              {row.gradable && row.mark?.total != null ? <T v="numeric">{fmt(row.mark.total)}<T v="caption" c="inkSecondary" style={{ fontWeight: "400" }}> / {fmt(max)}</T></T> : row.gradable ? <T c="inkTertiary">–</T> : null}
            </View>
          ) : null}
          <View style={{ flex: 1 }}><GradePill row={row} /></View>
          <View style={{ flex: 1.5 }}>
            {row.verify === "decided" ? (
              <T v="footnote" style={{ fontWeight: "500" }}>✓ {meta.decision[row.decision ?? ""]}</T>
            ) : row.verify ? (
              <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                {row.verify !== "not_needed" ? <Dot color={c.warning} /> : null}
                <T v="footnote" c={row.verify === "not_needed" ? "inkTertiary" : "warning"} style={{ fontWeight: row.verify === "not_needed" ? "400" : "600" }}>{meta.verify[row.verify]}</T>
              </View>
            ) : (
              <T v="footnote" c="inkTertiary">{WAITING[row.status] ?? row.status}</T>
            )}
          </View>
          {wide ? (
            <View style={{ flex: 2, gap: 2 }}>
              {row.tier ? <Tier tier={row.tier} label={meta.tier[row.tier] ?? row.tier} /> : null}
              {row.top && row.tier !== "SEED" && row.tier !== "REF" ? (
                <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }} numberOfLines={1}>{pct(row.coverage)} found elsewhere, closest {row.top.filename}</T>
              ) : null}
            </View>
          ) : null}
        </View>
      </Tappable>
    </Reveal>
  );
}

export function AssignmentScreen({ aid }: { aid: string }) {
  const c = useColors();
  const { navigate } = useRouter();
  const meta = useMeta();
  const { toast, confirm } = useFeedback();
  const { width } = useWindowDimensions();
  const wide = width >= 900;
  const [query, setQuery] = useQuery();
  const grade = query.get("grade") ?? "", status = query.get("status") ?? "", tier = query.get("tier") ?? "", q = query.get("q") ?? "";
  const [search, setSearch] = useState(q);
  const ring = useFocusRing();

  const path = `/a/${aid}?` + new URLSearchParams({ grade, status, tier, q }).toString();
  const page = useGet<Dashboard>(path);
  const stat = useGet<Status>(`/a/${aid}/status`);
  const d = page.data;
  const id = Number(aid);

  // Refresh the list only when something changed on the server.
  const stamp = useRef("");
  useEffect(() => {
    if (stat.data && stat.data.stamp !== stamp.current) {
      if (stamp.current) page.reload();
      stamp.current = stat.data.stamp;
    }
  }, [stat.data]); // eslint-disable-line react-hooks/exhaustive-deps
  useInterval(stat.reload, isBusy(stat.data) ? 2000 : 10000);

  // Search waits for a pause in typing before it asks the server.
  useEffect(() => {
    if (search === q) return;
    const t = setTimeout(() => setQuery({ q: search }), 250);
    return () => clearTimeout(t);
  }, [search]); // eslint-disable-line react-hooks/exhaustive-deps

  const onDone = useCallback(() => { stat.reload(); page.reload(); }, [stat.reload, page.reload]);
  const uploader = useUploader(id, "submission", onDone);
  const over = useWindowDrop(uploader.send);

  if (!d) return <Page bar={<AppBar title="Assignment" crumbs={[{ label: "Assignments", to: "/" }]} />}><Loading error={page.error} retry={page.reload} /></Page>;

  const a = d.assignment;
  const total = Object.values(d.counts).reduce((x, y) => x + y, 0);
  const s = stat.data ?? { ...d.counts, rescanning: d.rescanning, stamp: "" };
  const gradable = Object.values(d.grades).reduce((x, y) => x + y, 0);
  const waiting = (d.verify.awaiting ?? 0) + (d.verify.recheck ?? 0);
  const filtered = !!(grade || status || tier || q);
  const download = (p: string) => { window.location.href = p; };
  const remove = async () => {
    if (!(await confirm(`Delete ${a.name} and its ${d.total} ${d.total === 1 ? "submission" : "submissions"}, grades and integrity decisions? Other assignments are not touched. This cannot be undone.`, { confirmLabel: `Delete ${a.name}`, danger: true }))) return;
    try {
      await api.del(`/a/${aid}`);
      toast(`${a.name} deleted.`);
      navigate("/");
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
    }
  };

  const bar = (
    <AppBar
      title={a.name}
      subtitle={(a.deadline_at ? `Due ${when(a.deadline_at)}. ` : "") + "Click a student to open their PDF and grade it."}
      crumbs={[{ label: "Assignments", to: "/" }]}
      actions={
        <>
          <Menu label="More" items={[
            { label: "Assignment setup", onPress: () => navigate(`/a/${aid}/setup`) },
            { label: "Similar groups", onPress: () => navigate(`/a/${aid}/clusters`) },
            { label: "Calibrate the similarity check", onPress: () => navigate(`/a/${aid}/calibrate`) },
            "divider",
            { label: "Export grades (CSV)", onPress: () => download(`/a/${aid}/grades.csv`) },
            { label: "Export integrity report (CSV)", onPress: () => download(`/a/${aid}/export.csv`) },
            "divider",
            { label: "Delete this assignment…", onPress: remove },
          ]} />
          <Button label="Setup" onPress={() => navigate(`/a/${aid}/setup`)} />
          <FilePicker accept="application/pdf,.pdf" onFiles={uploader.send}>{(open) => <Button variant="primary" icon="upload" label="Add PDFs" onPress={open} />}</FilePicker>
        </>
      }
    />
  );

  return (
    <Page bar={bar}>
      <Reveal>
        <Card pad={0}>
          <View style={{ flexDirection: "row", flexWrap: "wrap" }}>
            <Stat first label="Released" value={d.grades.released ?? 0} of={gradable} note="" onPress={() => setQuery({ grade: "released" })} />
            <Stat label="Drafts" value={d.grades.draft ?? 0} note="Saved, not yet released" onPress={() => setQuery({ grade: "draft" })} />
            <Stat label="Not graded" value={d.grades.none ?? 0} note={`${a.rubric.length} ${a.rubric.length === 1 ? "part" : "parts"}, out of ${fmt(a.max_score)}`} onPress={() => setQuery({ grade: "none" })} />
            <Stat label="Integrity checks" value={waiting} warn={!!waiting} note={waiting ? `flagged ${waiting === 1 ? "submission awaits" : "submissions await"} your decision` : "nothing waiting"} onPress={() => setQuery({ status: "awaiting" })} />
          </View>
        </Card>
      </Reveal>

      <Reveal delay={60}>
        <Card style={[{ borderStyle: "dashed", gap: spacing.sm, padding: total ? spacing.md : spacing.lg }, over && { borderColor: c.anchor, backgroundColor: c.anchorSoft }]}>
          <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.sm }}>
            <Icon name="upload" color={c.anchor} />
            <T v="bodyStrong">Drop student PDFs anywhere on this page</T>
            <T c="inkTertiary">or</T>
            <FilePicker accept="application/pdf,.pdf" onFiles={uploader.send}>{(open) => <T accessibilityRole="link" onPress={open} c="anchor" style={web({ cursor: "pointer" })}>choose files</T>}</FilePicker>
          </View>
          {!total ? <T v="footnote" c="inkSecondary">Name files <T v="mono" style={{ backgroundColor: c.surfaceAlt }}>studentid_anything.pdf</T> to tie them to a student. You can change the student on each submission later.</T> : null}
          {uploader.lines.map((l, i) => <T key={i} v="footnote" c={i ? "negative" : "inkSecondary"}>{l}</T>)}
          {s.rescanning ? <RescanStatus r={s.rescan} /> : null}
          {total && !s.rescanning ? (
            <View style={{ gap: 4 }}>
              <ProgressBar value={((s.done + s.failed) / (total || 1)) * 100} />
              <T v="footnote" c="inkSecondary">
                {s.done} read, {s.processing} in progress, {s.queued} waiting{s.failed ? <T v="footnote" c="negative" style={{ fontWeight: "700" }}>, {s.failed} could not be read</T> : null}
              </T>
            </View>
          ) : null}
        </Card>
      </Reveal>

      {d.failed.length ? (
        <Card pad={spacing.md}>
          <Disclosure title={`${d.failed.length} ${d.failed.length === 1 ? "file" : "files"} could not be read`}>
            <View style={{ gap: 4, paddingVertical: 8 }}>
              {d.failed.map((f, i) => <T key={i} v="footnote"><T v="footnote" style={{ fontWeight: "700" }}>{f.filename}</T>: {f.error}</T>)}
              <View style={{ flexDirection: "row", marginTop: 8 }}>
                <Button label="Try again" onPress={async () => { await api.post(`/a/${aid}/retry`); toast("Trying those files again."); onDone(); }} />
              </View>
            </View>
          </Disclosure>
        </Card>
      ) : null}

      {!a.has_rubric ? (
        <T v="footnote" c="inkSecondary">Marks are one overall score out of {fmt(a.max_score)}. <T v="footnote" c="anchor" onPress={() => navigate(`/a/${aid}/setup`)} style={web({ cursor: "pointer" })}>Add a rubric</T> to mark part by part.</T>
      ) : null}

      <Reveal delay={100}>
        <Card pad={0}>
          <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.sm, padding: spacing.md, zIndex: 5 }}>
            <View style={[{ flex: 1, minWidth: 200, maxWidth: 300, flexDirection: "row", alignItems: "center", gap: 8, height: 40, paddingHorizontal: 12, borderRadius: radii.sm, borderWidth: 1, backgroundColor: c.surfaceAlt }, ring.style]}>
              <Icon name="search" size={16} color={c.inkTertiary} />
              <TextInput
                {...ring.handlers} value={search} onChangeText={setSearch} placeholder="Search students or files" placeholderTextColor={c.inkDisabled}
                accessibilityLabel="Search students or files" style={web({ flex: 1, color: c.ink, fontSize: 14, outlineStyle: "none" })}
              />
            </View>
            <Select label="Grade status" width={150} value={grade} onChange={(v) => setQuery({ grade: v })}
              options={[{ value: "", label: "All grades" }, { value: "none", label: "Not graded" }, { value: "draft", label: "Draft" }, { value: "released", label: "Released" }]} />
            <Select label="Integrity" width={230} value={status} onChange={(v) => setQuery({ status: v })}
              options={[{ value: "", label: "Any integrity state" }, { value: "awaiting", label: "Awaiting your decision" }, { value: "decided", label: "Decided" },
                ...Object.entries(meta.decision).map(([k, v]) => ({ value: k, label: `Decided: ${v.toLowerCase()}` }))]} />
            <Select label="Similarity" width={180} value={tier} onChange={(v) => setQuery({ tier: v })}
              options={[{ value: "", label: "Any similarity" }, ...Object.entries(meta.tier).map(([k, v]) => ({ value: k, label: v }))]} />
            <T v="footnote" c="inkSecondary" accessibilityLiveRegion="polite">
              {filtered ? `Showing ${d.rows.length} of ${d.total}` : `${d.total} ${d.total === 1 ? "submission" : "submissions"}`}
            </T>
            {filtered ? <Button variant="plain" label="Clear" onPress={() => { setSearch(""); setQuery({ grade: "", status: "", tier: "", q: "" }); }} /> : null}
          </View>
          {d.rows.length ? (
            <View>
              <View style={{ flexDirection: "row", gap: spacing.md, paddingHorizontal: spacing.lg, paddingVertical: 8, borderTopWidth: 1, borderTopColor: c.hairline }}>
                <T v="footnote" c="inkSecondary" style={{ flex: 2.2 }}>Student</T>
                {wide ? <T v="footnote" c="inkSecondary" style={{ flex: 0.7, textAlign: "right" }}>Grade</T> : null}
                <T v="footnote" c="inkSecondary" style={{ flex: 1 }}>Grade status</T>
                <T v="footnote" c="inkSecondary" style={{ flex: 1.5 }}>Integrity</T>
                {wide ? <T v="footnote" c="inkSecondary" style={{ flex: 2 }}>Similarity</T> : null}
              </View>
              {d.rows.map((r, i) => <SubRow key={r.id} row={r} max={a.max_score} wide={wide} index={i} />)}
            </View>
          ) : (
            <View style={{ borderTopWidth: 1, borderTopColor: c.hairline }}>
              <Empty>{status === "awaiting" ? "Nothing is waiting for your integrity decision." : filtered ? "No submissions match these filters." : "No submissions yet. Drop PDFs here or use Add PDFs."}</Empty>
            </View>
          )}
        </Card>
      </Reveal>
    </Page>
  );
}
