import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Image, View, useWindowDimensions } from "react-native";

import { api, useGet, useInterval } from "../api/client";
import type { Item, Submission } from "../api/types";
import { fmt, GRADE_LABEL, pct, useMeta, when } from "../meta";
import { subPath, useFilterQs, useQuery, useRouter } from "../router";
import { radii, spacing, useColors } from "../theme";
import { AppBar, Loading, useFeedback } from "../ui/chrome";
import { IgnoreRegion, MaskedThumb } from "../ui/IgnoreRegion";
import { IgnoreText } from "../ui/IgnoreText";
import { useDismiss } from "../ui/useDismiss";
import {
  Button, Card, Choices, Disclosure, Dot, Field, Icon, LinkText, Pill, Reveal, Segmented, T, Tappable, Tier, web,
} from "../ui/primitives";

type Tab = "grade" | "integrity";

// ---------- grading tab ----------

function StudentCard({ sub, onSaved }: { sub: Submission; onSaved: () => void }) {
  const c = useColors();
  const { toast } = useFeedback();
  const [open, setOpen] = useState(!sub.student);
  const [sid, setSid] = useState(sub.student?.student_id ?? "");
  const [name, setName] = useState(sub.student?.name ?? "");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!sid.trim()) return toast("Enter the student ID.", { tone: "error" });
    setBusy(true);
    try {
      await api.put(`/s/${sub.id}/student`, { student_id: sid, name });
      toast("Student saved. The similarity check is re-scanning this assignment.");
      setOpen(false);
      onSaved();
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
    }
    setBusy(false);
  };

  return (
    <View style={{ borderRadius: radii.md, backgroundColor: c.surfaceAlt, padding: spacing.ms, gap: spacing.ms }}>
      <Tappable onPress={() => setOpen(!open)} label="Change student" style={{ borderRadius: radii.xs }}>
        <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8 }}>
          <T v="footnote" c="inkSecondary">Student</T>
          <T v="bodyStrong" style={{ flex: 1 }} numberOfLines={1}>
            {sub.student ? sub.student.name || sub.student.student_id : "Not set"}
            {sub.student?.name ? <T v="footnote" c="inkSecondary" style={{ fontWeight: "400" }}>  {sub.student.student_id}</T> : null}
          </T>
          {!open ? <T v="footnote" c="anchor">Change</T> : null}
        </View>
      </Tappable>
      {open ? (
        <Reveal y={-4} style={{ gap: spacing.ms }}>
          <View style={{ flexDirection: "row", gap: spacing.sm }}>
            <View style={{ flex: 1 }}><Field label="Student ID" value={sid} onChangeText={setSid} autoComplete="off" /></View>
            <View style={{ flex: 1 }}><Field label="Name" hint="optional" value={name} onChangeText={setName} autoComplete="off" /></View>
          </View>
          <T v="footnote" c="inkSecondary">Files from the same student are never compared with each other. Saving re-scans the assignment.</T>
          <View style={{ flexDirection: "row" }}><Button label="Save student" onPress={save} loading={busy} /></View>
        </Reveal>
      ) : null}
    </View>
  );
}

function GradeTab({ sub, reload, goIntegrity, marks, setMarks, feedback, setFeedback, dirty, save }: {
  sub: Submission; reload: () => void; goIntegrity: () => void; marks: Record<string, string>; setMarks: (m: Record<string, string>) => void;
  feedback: string; setFeedback: (v: string) => void; dirty: boolean; save: (action: string) => Promise<boolean>;
}) {
  const c = useColors();
  const { navigate } = useRouter();
  const qs = useFilterQs();
  const needsCheck = sub.verify === "awaiting" || sub.verify === "recheck";
  const filled = Object.values(marks).filter((v) => v.trim() !== "");
  const total = filled.length ? filled.reduce((s, v) => s + (parseFloat(v) || 0), 0) : null;
  const mark = sub.mark;
  const released = mark?.status === "released";
  const [busy, setBusy] = useState("");

  const run = (action: string, after?: () => void) => async () => {
    setBusy(action);
    if (await save(action)) after?.();
    setBusy("");
  };

  if (sub.is_seed || sub.is_reference) {
    return <T v="footnote" c="inkSecondary">This file is {sub.is_seed ? "a past cohort's work" : "a known source"}. It is only used for the similarity check and is not graded.</T>;
  }

  return (
    <View style={{ gap: spacing.md }}>
      {needsCheck ? (
        <View style={{ borderRadius: radii.md, borderWidth: 1, borderColor: c.warningBorder, backgroundColor: c.warningSoft, padding: spacing.md, gap: spacing.sm }}>
          <T v="footnote"><T v="footnote" style={{ fontWeight: "700" }}>Integrity check needed.</T> The similarity check flagged this submission. You can mark it now, but the grade can only be released after you record your decision.</T>
          <View style={{ flexDirection: "row" }}><Button small label="Review integrity" onPress={goIntegrity} /></View>
        </View>
      ) : sub.status === "queued" || sub.status === "processing" ? (
        <View style={{ borderRadius: radii.md, borderWidth: 1, borderColor: c.hairline, backgroundColor: c.surfaceAlt, padding: spacing.md }}>
          <T v="footnote">The similarity check is still reading this file. You can mark it now and release the grade when the check finishes.</T>
        </View>
      ) : null}

      <View style={{ borderRadius: radii.md, borderWidth: 1, borderColor: c.hairline, overflow: "hidden" }}>
        {sub.assignment.rubric.map((cr, i) => (
          <View key={cr.name} style={{ flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.ms, borderTopWidth: i ? 1 : 0, borderTopColor: c.hairline }}>
            <T v="callout" style={{ flex: 1 }}>{cr.name}</T>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
              <View style={{ width: 84 }}>
                <Field
                  value={marks[cr.name] ?? ""} onChangeText={(v) => setMarks({ ...marks, [cr.name]: v })} autoFocus={i === 0}
                  keyboardType="decimal-pad" inputMode="decimal" accessibilityLabel={`${cr.name} marks`} style={{ textAlign: "right", fontWeight: "600" }}
                />
              </View>
              <T v="footnote" c="inkSecondary" style={{ minWidth: 40 }}>/ {fmt(cr.points)}</T>
            </View>
          </View>
        ))}
      </View>

      <View style={{ flexDirection: "row", justifyContent: "space-between", alignItems: "baseline", paddingHorizontal: 4 }}>
        <T v="footnote" c="inkSecondary">Total</T>
        <T v="title2">{total === null ? "–" : fmt(total)} <T v="footnote" c="inkSecondary" style={{ fontWeight: "400" }}>/ {fmt(sub.assignment.max_score)}</T></T>
      </View>

      <Field label="Feedback" hint="shown to the student with the grade" value={feedback} onChangeText={setFeedback} rows={6} />

      <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, flexWrap: "wrap" }}>
        <Pill label={released ? "✓ Released" : mark ? "Draft" : "Not graded"} tone={released ? "positive" : mark ? "anchor" : "neutral"} />
        {mark ? <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }}>Last saved {when(mark.updated_at)}</T> : null}
        {dirty ? <T v="caption" c="warning">Unsaved changes</T> : null}
      </View>

      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.sm }}>
        <Button label="Save draft" title="Save draft (Ctrl+S)" onPress={run("save")} loading={busy === "save"} />
        {released ? (
          <>
            <Button label="Update released grade" onPress={run("release")} loading={busy === "release"} />
            <Button variant="plain" label="Move back to draft" onPress={run("unrelease")} loading={busy === "unrelease"} />
          </>
        ) : (
          <>
            <Button variant="primary" label="Release grade" disabled={needsCheck} title={needsCheck ? "Record your integrity decision first" : undefined} onPress={run("release")} loading={busy === "release"} />
            {sub.nav.next_ungraded ? (
              <Button variant="primary" label="Release and next" disabled={needsCheck} onPress={run("release", () => navigate(subPath(sub.nav.next_ungraded!, qs)))} loading={busy === "next"} />
            ) : null}
          </>
        )}
      </View>
    </View>
  );
}

// ---------- integrity tab ----------

const SERIES = ["series", "series", "series", "series", "series"] as const;

function IntegrityTab({ sub, reload, showPage }: { sub: Submission; reload: () => void; showPage: (p: number) => void }) {
  const c = useColors();
  const { navigate } = useRouter();
  const qs = useFilterQs();
  const { toast, confirm } = useFeedback();
  const meta = useMeta();
  const dismiss = useDismiss();
  const last = sub.reviews[0] && sub.reviews[0].status in meta.decision ? sub.reviews[0] : null;
  const [choice, setChoice] = useState(sub.verify === "decided" && last ? last.status : "");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const color = (i: number) => (i < 5 ? c.series[i] : [c.anchor, c.negative, c.inkTertiary][i - 5]);

  const decide = async (status: string) => {
    if (!status) return toast("Choose a decision first.", { tone: "error" });
    setBusy(true);
    try {
      await api.post(`/s/${sub.id}/review`, { status, note });
      const next = sub.nav.next_flagged;
      toast(status === "unreviewed" ? "Decision withdrawn. This submission is waiting again." : `Decision saved: ${meta.decision[status]}.`, next ? { action: { label: "Next flagged submission", onPress: () => navigate(subPath(next, qs, "tab=integrity")) } } : undefined);
      setNote("");
      reload();
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
    }
    setBusy(false);
  };

  const ignore = async (it: Item) => {
    if (!(await confirm(`Ignore this content in every ${sub.assignment.name} submission, for example because it is starter code? Everything will be re-scanned.`, { confirmLabel: "Ignore everywhere" }))) return;
    await api.post(`/item/${it.id}/ignore`);
    toast("Ignored. Re-scanning the assignment.");
    reload();
  };

  if (sub.status !== "done") {
    return <T v="footnote" c="inkSecondary">{sub.status === "failed" ? `The similarity check could not read this file${sub.error ? `: ${sub.error}` : ""}. Try again from the submissions list.` : "The similarity check is still reading this file."}</T>;
  }

  const v = sub.verify;
  const slip = v === "decided" ? [c.anchorSoft, c.anchor, "solid"] : v === "not_needed" ? [c.surfaceAlt, c.hairline, "solid"] : [c.warningSoft, c.warningBorder, "dashed"];

  return (
    <View style={{ gap: spacing.md }}>
      <View style={[{ borderRadius: radii.md, borderWidth: 1, backgroundColor: slip[0], borderColor: slip[1], borderStyle: slip[2] as "solid" | "dashed", padding: spacing.md, gap: spacing.sm }]}>
        {v === "decided" && last ? (
          <><T v="headline">You decided: {meta.decision[last.status]}</T><T v="footnote" c="inkSecondary">{when(last.ts)}{last.note ? `. Note: ${last.note}` : ""}</T></>
        ) : v === "recheck" && last ? (
          <><T v="headline">New evidence since your decision</T><T v="footnote">You decided “{meta.decision[last.status].toLowerCase()}” on {when(last.ts)}. The suggestion is now stronger, so it needs your decision again.</T></>
        ) : v === "awaiting" ? (
          <>
            <T v="headline">Awaiting your decision</T>
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <T v="footnote">The app suggests</T>{sub.report.tier ? <Tier tier={sub.report.tier} label={meta.tier[sub.report.tier] ?? sub.report.tier} /> : null}
            </View>
            <T v="footnote">This points to evidence; it is not a finding. Check the matches below, then decide.</T>
          </>
        ) : (
          <><T v="headline">Nothing flagged</T><T v="footnote" c="inkSecondary">No decision is needed. You can still record one.</T></>
        )}

        <T v="footnote" c="inkSecondary" style={{ marginTop: 4 }}>{v === "decided" ? "Change your decision" : "Your decision"}</T>
        <Choices value={choice} onChange={setChoice} options={Object.entries(meta.decision).map(([value, label]) => ({ value, label }))} />
        <Field label="Note" hint={'required for "needs follow-up"; record what you checked'} value={note} onChangeText={setNote} rows={2} />
        <View style={{ flexDirection: "row", gap: spacing.sm, flexWrap: "wrap" }}>
          <Button variant="primary" label="Save decision" onPress={() => decide(choice)} loading={busy} />
          {last ? <Button variant="plain" label="Withdraw decision" onPress={() => decide("unreviewed")} /> : null}
        </View>
        {sub.reviews.length > 1 || (sub.reviews.length && !last) ? (
          <Disclosure title="Decision history">
            <View style={{ gap: 4, paddingVertical: 6 }}>
              {sub.reviews.map((r, i) => (
                <T key={i} v="footnote">{when(r.ts)}: {meta.decision[r.status] ?? "withdrawn"}{r.suggested ? <T v="footnote" c="inkTertiary"> (app suggested {(meta.tier[r.suggested] ?? "–").toLowerCase()})</T> : null}{r.note ? `. ${r.note}` : ""}</T>
              ))}
            </View>
          </Disclosure>
        ) : null}
      </View>

      <T v="overline" c="accent">Why the app suggests this</T>
      <View style={{ gap: 4 }}>{sub.report.reasons.map((r, i) => <T key={i} v="footnote">•  {r}</T>)}</View>
      <T v="footnote" c="inkSecondary">
        {pct(sub.report.coverage)} of this submission's distinctive content also appears elsewhere, compared with {sub.report.population} submissions. Content most students share, like expected output or the brief, counts little or not at all.
      </T>

      {sub.report.by_source.length ? (
        <>
          <T v="overline" c="accent">Where the matching content appears</T>
          <View style={{ flexDirection: "row", height: 8, borderRadius: 4, overflow: "hidden", backgroundColor: c.surfaceAlt }}>
            {sub.report.by_source.slice(0, 8).map((b, i) => <View key={b.submission_id} style={{ width: `${b.share * 100}%`, backgroundColor: color(i), borderRightWidth: 2, borderRightColor: c.surface }} />)}
          </View>
          {sub.report.by_source.map((b, i) => (
            <Tappable key={b.submission_id} href={`/s/${b.submission_id}?tab=integrity`} onPress={() => navigate(`/s/${b.submission_id}?tab=integrity`)} label={b.filename} style={{ borderRadius: radii.xs }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8, paddingVertical: 6 }}>
                <View style={{ width: 10, height: 10, borderRadius: 2, backgroundColor: color(i) }} />
                <T v="footnote" c="anchor" style={{ flex: 1 }} numberOfLines={1}>{b.filename}{b.is_reference ? <T v="caption" c="inkTertiary"> known source</T> : null}</T>
                <T v="numeric" style={{ fontSize: 13 }}>{pct(b.share)}</T>
                <T v="caption" c="inkTertiary" style={{ width: 64, textAlign: "right", fontWeight: "400" }}>{b.items} items</T>
              </View>
            </Tappable>
          ))}
        </>
      ) : null}

      {sub.flags.length ? (
        <>
          <T v="overline" c="accent">Signals to check</T>
          {sub.flags.map((f, i) => (
            <View key={i} style={{ borderTopWidth: 1, borderTopColor: c.hairline, paddingTop: spacing.sm, gap: 4 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
                <T v="bodyStrong">{meta.flag[f.type] ?? f.type}</T>
                <Pill label={f.severity} tone={f.severity === "high" ? "negative" : f.severity === "medium" ? "warning" : "neutral"} />
              </View>
              <T v="footnote">{f.summary}</T>
              <T v="footnote" c="inkSecondary">{f.help}</T>
              <Disclosure title="Show evidence"><T v="mono" style={{ backgroundColor: c.surfaceAlt, padding: 10, borderRadius: radii.xs }}>{JSON.stringify(f.evidence, null, 2)}</T></Disclosure>
            </View>
          ))}
        </>
      ) : null}

      <T v="overline" c="accent">Screenshots, figures and typed answers</T>
      <T v="footnote" c="inkSecondary">Highlighted items also appear in another submission. Weight is how distinctive an item is: 0 means many students have it.</T>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.ms }}>
        {sub.items.map((it) => (
          <View key={it.id} style={{ flexGrow: 1, flexBasis: 170, maxWidth: "100%", borderRadius: radii.md, borderWidth: 1, borderColor: it.matched ? c.warningBorder : c.hairline, borderLeftWidth: it.matched ? 3 : 1, borderLeftColor: it.matched ? c.warning : c.hairline, padding: spacing.sm, gap: 6 }}>
            <View style={{ flexDirection: "row", justifyContent: "space-between", flexWrap: "wrap", gap: 4 }}>
              <LinkText v="footnote" onPress={() => showPage(it.page)} style={{ fontWeight: "600", color: c.ink }}>{it.label.charAt(0).toUpperCase() + it.label.slice(1)}</LinkText>
              <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }}>weight {it.weight == null ? "–" : it.weight.toFixed(2)}{it.df && it.df > 1 ? `, in ${it.df} files` : ""}</T>
            </View>
            {it.thumb ? (
              <a href={`/i/${it.id}`} target="_blank" rel="noreferrer" title="Open this item and everyone who shares it in a new tab"><MaskedThumb src={it.thumb} alt={it.label} masks={it.masks} style={{ maxHeight: 160, margin: "0 auto", borderRadius: 4, cursor: "zoom-in" }} /></a>
            ) : (
              <a href={`/i/${it.id}`} target="_blank" rel="noreferrer" title="Open this item and everyone who shares it in a new tab" style={{ textDecoration: "none", color: "inherit" }}><T v="mono" style={{ backgroundColor: c.surfaceAlt, padding: 8, borderRadius: radii.xs, fontSize: 11, maxHeight: 128, overflow: "hidden" } as never}>{it.text}</T></a>
            )}
            {it.matches.length ? <a href={`/i/${it.id}`} target="_blank" rel="noreferrer" style={{ fontSize: 12, color: c.anchor, textDecoration: "none" }}>See all {it.matches.length} {it.matches.length === 1 ? "match" : "matches"} and why ↗</a> : null}
            {it.matches.length ? (
              <View style={{ gap: 2 }}>
                {it.matches.slice(0, 5).map((m) => (
                  <View key={m.id}>
                    <LinkText v="footnote" onPress={() => navigate(`/m/${m.id}`)}>{m.filename}</LinkText>
                    <View style={{ flexDirection: "row", gap: spacing.sm, alignItems: "center", flexWrap: "wrap" }}>
                      <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }}>{m.what}</T>
                      <LinkText v="caption" onPress={() => dismiss(m.id, reload)} style={{ color: c.negative }}>Not a match</LinkText>
                    </View>
                  </View>
                ))}
                {it.matches.length > 5 ? <T v="caption" c="inkTertiary">{it.matches.length - 5} more</T> : null}
                <LinkText v="caption" onPress={() => ignore(it)} style={{ marginTop: 4 }}>Ignore everywhere, it is given material</LinkText>
                <IgnoreText itemId={it.id} lines={it.lines} assignment={sub.assignment.name} onDone={reload} />
                <IgnoreRegion itemId={it.id} thumb={it.thumb} masks={it.masks} assignment={sub.assignment.name} onDone={reload} />
              </View>
            ) : null}
          </View>
        ))}
      </View>

      {sub.meta.heads.length ? (
        <>
          <T v="overline" c="accent">PDF metadata</T>
          <T v="footnote" c="inkSecondary">A weak signal: many programs write the same values. Matching cells are shaded.</T>
          <View style={web({ overflowX: "auto" })}>
            <table style={{ borderCollapse: "collapse", fontSize: 12.5, color: c.ink, width: "100%" }}>
              <thead>
                <tr>{["", "This file", ...sub.meta.heads].map((h, i) => <th key={i} style={{ textAlign: "left", padding: "4px 8px", color: c.inkSecondary, fontWeight: 400, borderBottom: `1px solid ${c.hairline}` }}>{h}</th>)}</tr>
              </thead>
              <tbody>
                {sub.meta.rows.map((row, i) => (
                  <tr key={i}>
                    <th style={{ textAlign: "left", padding: "4px 8px", color: c.inkSecondary, fontWeight: 400 }}>{row[0]}</th>
                    {row.slice(1).map((val, j) => <td key={j} style={{ padding: "4px 8px", background: j > 0 && val && val === row[1] ? c.warningSoft : undefined }}>{val}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </View>
        </>
      ) : null}
    </View>
  );
}

// ---------- screen ----------

export function GraderScreen({ sid }: { sid: string }) {
  const c = useColors();
  const { navigate, route } = useRouter();
  const { toast, confirm } = useFeedback();
  const { width } = useWindowDimensions();
  const [query, setQuery] = useQuery();
  const qs = useFilterQs();
  const { data, error, reload } = useGet<Submission>(`/s/${sid}${qs ? "?" + qs : ""}`);
  const [marks, setMarks] = useState<Record<string, string>>({});
  const [feedback, setFeedback] = useState("");
  const [dirty, setDirty] = useState(false);
  const [page, setPage] = useState(1);
  const loaded = useRef<number | null>(null);
  const tab: Tab = query.get("tab") === "integrity" ? "integrity" : "grade";
  const split = width >= 1000;

  // Fill the form once per submission (and after a save), never while the grader is typing.
  useEffect(() => {
    if (!data || (loaded.current === data.id && dirty)) return;
    loaded.current = data.id;
    setMarks(Object.fromEntries(data.assignment.rubric.map((cr) => [cr.name, data.mark?.scores[cr.name] != null ? fmt(data.mark.scores[cr.name]) : ""])));
    setFeedback(data.mark?.feedback ?? "");
    setDirty(false);
  }, [data]); // eslint-disable-line react-hooks/exhaustive-deps

  // Still being read: check back until the similarity check finishes.
  useInterval(reload, data && (data.status === "queued" || data.status === "processing") ? 3000 : null);

  const save = useCallback(async (action: string) => {
    if (!data) return false;
    try {
      const r = await api.post<{ status: string }>(`/s/${data.id}/mark`, { scores: marks, feedback, action });
      toast(action === "unrelease" ? "Grade moved back to draft." : r.status === "released" ? "Grade released." : "Draft saved. Students do not see drafts.");
      setDirty(false);
      await reload();
      return true;
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
      await reload();
      return false;
    }
  }, [data, marks, feedback, toast, reload]);

  // Keyboard: [ and ] move between submissions, Ctrl+S saves a draft.
  const keys = useRef({ save, data, qs });
  keys.current = { save, data, qs };
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const d = keys.current.data;
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); keys.current.save("save"); return; }
      if (e.ctrlKey || e.metaKey || e.altKey || !d || /INPUT|TEXTAREA|SELECT/.test((document.activeElement as HTMLElement)?.tagName ?? "")) return;
      if (e.key === "[" && d.nav.prev) navigate(subPath(d.nav.prev, keys.current.qs));
      if (e.key === "]" && d.nav.next) navigate(subPath(d.nav.next, keys.current.qs));
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  // Warn before leaving with unsaved marks.
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const meta = useMeta();
  const pdf = useMemo(() => `/s/${sid}/pdf#view=FitH&page=${page}`, [sid, page]);

  if (!data) return <View style={web({ minHeight: "100vh" })}><AppBar title="Submission" crumbs={[{ label: "Assignments", to: "/" }]} /><Loading error={error} retry={reload} /></View>;

  const a = data.assignment;
  const FILTER_NAMES: Record<string, string> = { grade: "grade", status: "integrity", tier: "similarity", flagged: "flags", q: "search" };
  const label = (k: string, v: string) => (k === "tier" ? meta.tier[v] : k === "grade" ? GRADE_LABEL[v] : k === "flagged" ? (v === "yes" ? "has flags" : "nothing flagged") : k === "status" ? (meta.decision[v] ?? ({ awaiting: "awaiting your decision", decided: "decided" } as Record<string, string>)[v]) : v) ?? v;
  const filterText = [...new URLSearchParams(qs)].map(([k, v]) => `${FILTER_NAMES[k] ?? k}: ${label(k, v)}`).join(", ");
  const name = data.student?.name || data.filename;
  const subtitle = [data.student ? data.student.student_id : "", data.student?.name ? data.filename : "", `${data.page_count || 0} pages`].filter(Boolean).join(", ") + (data.nav.filtered ? `. Filter, ${filterText}` : "");
  const needsCheck = data.verify === "awaiting" || data.verify === "recheck";
  const deleteFile = async () => {
    if (!(await confirm(`Delete ${name} (${data.filename})? Its marks, grade and integrity results are removed too, and the other submissions are re-scanned without it. This cannot be undone.`, { confirmLabel: "Delete this file", danger: true }))) return;
    try {
      await api.post(`/a/${a.id}/delete-files`, { ids: [data.id] });
      toast(`${name} deleted. Re-scanning.`);
      const go = data.nav.next ?? data.nav.prev;
      setDirty(false);
      navigate(go ? subPath(go, qs) : `/a/${a.id}${qs ? "?" + qs : ""}`);
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
    }
  };

  const bar = (
    <AppBar
      compact title={name} subtitle={subtitle}
      crumbs={[{ label: "Assignments", to: "/" }, { label: a.name, to: `/a/${a.id}${qs ? "?" + qs : ""}` }]}
      actions={
        <>
          <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
            <Pill label={data.nav.filtered ? "Filtered" : "All submissions"} tone={data.nav.filtered ? "anchor" : "neutral"} />
            <T v="footnote" c="inkSecondary">
              {data.nav.pos >= 0 ? `${data.nav.pos + 1} of ${data.nav.count}` : `${data.nav.count} ${data.nav.filtered ? "in this filter" : "total"}`}
            </T>
            {data.nav.filtered ? <Button small variant="plain" label="Clear filter" title="Stop filtering and move through every submission" onPress={() => navigate(subPath(sid, "", query.get("tab") ? `tab=${query.get("tab")}` : ""))} /> : null}
          </View>
          <Button label="Previous" title="Previous submission ( [ )" disabled={!data.nav.prev} onPress={() => navigate(subPath(data.nav.prev!, qs))} />
          <Button label="Next" title="Next submission ( ] )" disabled={!data.nav.next} onPress={() => navigate(subPath(data.nav.next!, qs))} />
          <Button label="Delete file" variant="danger" title="Delete this uploaded file and its results" onPress={deleteFile} />
          <Button label="Open PDF" onPress={() => window.open(`/s/${sid}/pdf`, "_blank", "noopener")} />
        </>
      }
    />
  );

  return (
    <View style={web({ minHeight: "100vh", height: split ? "100vh" : undefined })}>
      {bar}
      <View style={{ flex: 1, flexDirection: split ? "row" : "column", minHeight: 0 }}>
        <View style={web({ flex: split ? 1 : undefined, height: split ? undefined : "75vh", minHeight: split ? 0 : 420, minWidth: 0, backgroundColor: c.surfaceAlt, borderRightWidth: split ? 1 : 0, borderRightColor: c.hairline })}>
          <iframe key={`${sid}`} src={pdf} title={data.filename} style={{ width: "100%", height: "100%", border: 0, display: "block", background: "transparent" }} />
        </View>
        <View style={web({ width: split ? 440 : "100%", backgroundColor: c.surface, overflowY: split ? "auto" : "visible" })}>
          <Reveal key={sid} y={8} style={{ padding: spacing.md, paddingBottom: spacing.xl, gap: spacing.md }}>
            <Segmented<Tab>
              value={tab} onChange={(t) => setQuery({ tab: t === "grade" ? "" : t })}
              options={[{ value: "grade", label: "Grade" }, { value: "integrity", label: "Integrity", dot: needsCheck }]}
            />
            <StudentCard key={data.id} sub={data} onSaved={reload} />
            {tab === "grade" ? (
              <GradeTab sub={data} reload={reload} goIntegrity={() => setQuery({ tab: "integrity" })} marks={marks} feedback={feedback} dirty={dirty}
                setMarks={(m) => { setMarks(m); setDirty(true); }} setFeedback={(v) => { setFeedback(v); setDirty(true); }} save={save} />
            ) : (
              <IntegrityTab sub={data} reload={reload} showPage={setPage} />
            )}
          </Reveal>
        </View>
      </View>
    </View>
  );
}
