import { useCallback, useEffect, useState } from "react";
import { View } from "react-native";

import { api, useGet } from "../api/client";
import type { Dashboard } from "../api/types";
import { fmt } from "../meta";
import { useRouter } from "../router";
import { spacing, useColors } from "../theme";
import { AppBar, Loading, Page, useFeedback, useWindowDrop } from "../ui/chrome";
import { Button, Card, DateField, Field, FilePicker, Icon, LinkText, Reveal, Segmented, T, web } from "../ui/primitives";
import { useUploader } from "../upload";

export function SetupScreen({ aid }: { aid: string }) {
  const c = useColors();
  const { navigate } = useRouter();
  const { toast } = useFeedback();
  const { data, error, reload } = useGet<Dashboard>(`/a/${aid}`);
  const [form, setForm] = useState({ name: "", start_at: "", deadline_at: "", rubric_text: "", max_score: "100", notes: "" });
  const [saving, setSaving] = useState(false);
  const [mode, setMode] = useState<"seed" | "reference">("seed");
  const [brief, setBrief] = useState<File[]>([]);
  const [busy, setBusy] = useState("");
  const id = Number(aid);
  const uploader = useUploader(id, mode, reload);
  const over = useWindowDrop(uploader.send);

  // Load the saved values into the form once.
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (!data || ready) return;
    const a = data.assignment;
    setForm({ name: a.name, start_at: a.start_at ?? "", deadline_at: a.deadline_at ?? "", rubric_text: a.rubric_text, max_score: fmt(a.max_score), notes: a.notes ?? "" });
    setReady(true);
  }, [data, ready]);

  const set = (k: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [k]: v }));
  const crumbs = (name?: string) => [{ label: "Assignments", to: "/" }, { label: name ?? "Assignment", to: `/a/${aid}` }];

  const save = async () => {
    setSaving(true);
    try {
      await api.put(`/a/${aid}`, { ...form, max_score: parseFloat(form.max_score) || 100 });
      toast("Saved.");
      reload();
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
    }
    setSaving(false);
  };

  const addBrief = useCallback(async () => {
    setBusy("brief");
    try {
      const fd = new FormData();
      brief.forEach((f) => fd.append("files", f));
      const r = await api.post<{ fingerprints: number }>(`/a/${aid}/boilerplate`, fd);
      toast(`Brief added (${r.fingerprints} fingerprints). Re-scanning.`);
      setBrief([]);
      reload();
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
    }
    setBusy("");
  }, [brief, aid, toast, reload]);

  if (!data || !ready) return <Page bar={<AppBar title="Assignment setup" crumbs={crumbs()} />} narrow><Loading error={error} retry={reload} /></Page>;
  const a = data.assignment;
  const hasRubric = form.rubric_text.trim() !== "";

  return (
    <Page bar={<AppBar title="Assignment setup" crumbs={crumbs(a.name)} />} narrow>
      <Reveal>
        <Card style={{ gap: spacing.md }}>
          <T v="title3">Details</T>
          <Field label="Assignment name" value={form.name} onChangeText={set("name")} />
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
            <View style={{ flex: 1, minWidth: 200 }}><DateField label="Opens" hint="optional" value={form.start_at} onChange={set("start_at")} /></View>
            <View style={{ flex: 1, minWidth: 200 }}><DateField label="Deadline" hint="optional" value={form.deadline_at} onChange={set("deadline_at")} /></View>
          </View>
          <Field label="Rubric" hint="One part per line, as Name | points. Leave empty to give one overall mark." value={form.rubric_text} onChangeText={set("rubric_text")} rows={5} spellCheck={false}
            placeholder={"Part A: parsing | 10\nPart B: output table | 10\nPart C: graph and discussion | 5"} />
          <Field label="Out of" hint="Used when there is no rubric" value={form.max_score} onChangeText={set("max_score")} editable={!hasRubric} keyboardType="decimal-pad" style={hasRubric ? { opacity: 0.5 } : undefined} />
          <Field label="Notes" value={form.notes} onChangeText={set("notes")} rows={2} />
          <View style={{ flexDirection: "row" }}><Button variant="primary" label="Save" onPress={save} loading={saving} /></View>
        </Card>
      </Reveal>

      <Reveal delay={60}>
        <Card style={[{ borderStyle: "dashed", gap: spacing.sm }, over && { borderColor: c.anchor, backgroundColor: c.anchorSoft }]}>
          <T v="title3">Comparison files</T>
          <T v="footnote" c="inkSecondary">Work the similarity check compares against but never grades or flags. {data.compared.seed} past cohort, {data.compared.reference} known source {data.compared.reference === 1 ? "file" : "files"} added.</T>
          <Segmented value={mode} onChange={setMode} small options={[{ value: "seed", label: "Past cohort" }, { value: "reference", label: "Known source" }]} />
          <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 8 }}>
            <Icon name="upload" color={c.anchor} />
            <T v="bodyStrong">Drop PDFs here</T><T c="inkTertiary">or</T>
            <FilePicker accept="application/pdf,.pdf" onFiles={uploader.send}>{(open) => <T accessibilityRole="link" onPress={open} c="anchor" style={web({ cursor: "pointer" })}>choose files</T>}</FilePicker>
          </View>
          {uploader.lines.map((l, i) => <T key={i} v="footnote" c={i ? "negative" : "inkSecondary"}>{l}</T>)}
        </Card>
      </Reveal>

      <Reveal delay={120}>
        <Card style={{ gap: spacing.md }}>
          <T v="title3">Brief and starter material</T>
          <View style={{ gap: 4 }}>
            <T v="bodyStrong">Anything matching these files is ignored by the similarity check.</T>
            <T v="footnote" c="inkSecondary">{data.wl_count} fingerprints ignored now.</T>
          </View>
          <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.sm }}>
            <FilePicker accept=".pdf,.txt,.py,.java,.c,.cpp,.md" onFiles={setBrief}>{(open) => <Button label={brief.length ? "Choose different files" : "Choose files"} icon="file" onPress={open} />}</FilePicker>
            <T v="footnote" c="inkSecondary">{brief.length ? brief.map((f) => f.name).join(", ") : "No file chosen"}</T>
          </View>
          <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.sm }}>
            <Button label="Ignore this content and re-scan" onPress={addBrief} disabled={!brief.length} loading={busy === "brief"} />
            <Button label="Re-scan similarity" onPress={async () => { await api.post(`/a/${aid}/rescan`); toast("Re-scan started. Scores update when it finishes."); }} />
            <T v="footnote" c="inkSecondary">Do this after changing thresholds in <LinkText v="footnote" onPress={() => navigate("/settings")}>Settings</LinkText>.</T>
          </View>
        </Card>
      </Reveal>
    </Page>
  );
}
