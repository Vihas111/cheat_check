import { useEffect, useState } from "react";
import { View, useWindowDimensions } from "react-native";

import { api, useGet } from "../api/client";
import type { Settings } from "../api/types";
import { useRouter } from "../router";
import { monoFamily, spacing, useColors } from "../theme";
import { AppBar, Loading, Page, useFeedback } from "../ui/chrome";
import { Button, Card, Field, FilePicker, Reveal, Select, T } from "../ui/primitives";

export function SettingsScreen() {
  const c = useColors();
  const { toast, confirm } = useFeedback();
  const { width } = useWindowDimensions();
  const { data, error, reload } = useGet<Settings>("/settings");
  const [values, setValues] = useState<Record<string, string>>({});
  const [ready, setReady] = useState(false);
  const [roster, setRoster] = useState<File | null>(null);
  const [erase, setErase] = useState("");
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (!data || ready) return;
    setValues(Object.fromEntries(data.fields.map((f) => [f.name, String(f.value)])));
    setReady(true);
  }, [data, ready]);

  const bar = <AppBar title="Settings" crumbs={[{ label: "Assignments", to: "/" }]} />;
  if (!data || !ready) return <Page bar={bar}><Loading error={error} retry={reload} /></Page>;

  const attempt = async (key: string, fn: () => Promise<string>) => {
    setBusy(key);
    try { toast(await fn()); } catch (e) { toast((e as Error).message, { tone: "error" }); }
    setBusy("");
  };

  const loadRoster = () => attempt("roster", async () => {
    const fd = new FormData();
    fd.append("file", roster!);
    const r = await api.post<{ loaded: number }>("/settings/roster", fd);
    setRoster(null);
    reload();
    return `Roster loaded: ${r.loaded} students`;
  });

  const saveValues = () => attempt("save", async () => {
    await api.put("/settings", { values });
    return "Saved. Use Re-scan on an assignment to apply new thresholds.";
  });

  const doErase = async () => {
    if (!(await confirm("Delete every assignment, submission, grade, decision and stored file? This cannot be undone.", { confirmLabel: "Erase all data", danger: true }))) return;
    attempt("erase", async () => {
      await api.post("/settings/erase", { confirm: erase });
      setErase("");
      reload();
      return "All data erased.";
    });
  };

  const cols = width >= 900 ? 2 : 1;

  return (
    <Page bar={bar}>
      <View style={{ flexDirection: cols === 2 ? "row" : "column", gap: spacing.md, alignItems: "flex-start" }}>
        <Reveal style={{ flex: 1, width: "100%" }}>
          <Card style={{ gap: spacing.sm }}>
            <T v="title3">Class roster</T>
            <T>{data.roster} students loaded. Use a CSV with columns <T v="mono" style={{ backgroundColor: c.surfaceAlt }}>student_id,name,username,email</T>; only <T v="mono" style={{ backgroundColor: c.surfaceAlt }}>student_id</T> is required.</T>
            <T v="footnote" c="inkSecondary">The roster links files to students and spots screenshots that show another student's name, ID, username or email.</T>
            <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: spacing.sm }}>
              <FilePicker accept=".csv" multiple={false} onFiles={(f) => setRoster(f[0] ?? null)}>{(open) => <Button label="Choose CSV" icon="file" onPress={open} />}</FilePicker>
              <T v="footnote" c="inkSecondary">{roster ? roster.name : "No file chosen"}</T>
              <Button variant="primary" label="Load roster" disabled={!roster} loading={busy === "roster"} onPress={loadRoster} />
            </View>
          </Card>
        </Reveal>
        <Reveal delay={50} style={{ flex: 1, width: "100%" }}>
          <Card style={{ gap: spacing.sm }}>
            <T v="title3">Ignored content</T>
            {data.ignored.length ? data.ignored.map((w, i) => (
              <View key={i} style={{ flexDirection: "row", alignItems: "center", gap: spacing.sm, borderTopWidth: 1, borderTopColor: c.hairline, paddingTop: 8 }}>
                <View style={{ flex: 1 }}>
                  <T v="footnote" style={{ fontWeight: "600" }}>{w.kind === "image" ? "images" : "text"} · {w.scope || "all assignments"} · {w.pieces} pieces</T>
                  <T v="caption" c="inkTertiary" style={{ fontWeight: "400" }}>{w.reason}</T>
                </View>
                <Button small label="Stop ignoring" onPress={() => attempt("wl" + i, async () => {
                  await api.post("/settings/whitelist/delete", { kind: w.kind, scope: w.scope ?? "", reason: w.reason ?? "" });
                  reload();
                  return "Removed. Re-scan the assignment to apply.";
                })} />
              </View>
            )) : <T v="footnote" c="inkSecondary">Nothing is ignored yet. Upload the brief on an assignment's setup panel, or use "Ignore everywhere" on a matched item.</T>}
          </Card>
        </Reveal>
      </View>

      <Reveal delay={100}>
        <Card style={{ gap: spacing.md }}>
          <View style={{ gap: 4 }}>
            <T v="title3">Similarity check thresholds</T>
            <T v="footnote" c="inkSecondary">Reading engines found: {data.engines.join(", ") || "none. Install rapidocr-onnxruntime or tesseract"}. All reading happens on this computer. Saved values apply after you re-scan an assignment.</T>
          </View>
          <View style={{ flexDirection: "row", flexWrap: "wrap", columnGap: spacing.xl }}>
            {data.fields.map((f) => (
              <View key={f.name} style={{ flexBasis: cols === 2 ? "47%" : "100%", flexGrow: 1, flexDirection: "row", alignItems: "center", gap: spacing.md, paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: c.hairline }}>
                <View style={{ flex: 1 }}>
                  <T v="footnote" style={{ fontFamily: monoFamily, fontWeight: "600" }}>{f.name}</T>
                  <T v="caption" c="inkSecondary" style={{ fontWeight: "400" }}>{f.help}</T>
                </View>
                <View style={{ width: 150 }}>
                  {f.name === "ocr_device" ? (
                    <Select label="ocr_device" value={values[f.name]} onChange={(v) => setValues({ ...values, [f.name]: v })} options={["auto", "cpu", "cuda", "directml"].map((e) => ({ value: e, label: e }))} />
                  ) : f.name === "ocr_engine" ? (
                    <Select label="ocr_engine" value={values[f.name]} onChange={(v) => setValues({ ...values, [f.name]: v })} options={["auto", "rapidocr", "tesseract"].map((e) => ({ value: e, label: e }))} />
                  ) : (
                    <Field value={values[f.name]} onChangeText={(v) => setValues({ ...values, [f.name]: v })} accessibilityLabel={f.name} keyboardType={f.type === "str" ? "default" : "decimal-pad"} />
                  )}
                </View>
              </View>
            ))}
          </View>
          <View style={{ flexDirection: "row" }}><Button variant="primary" label="Save settings" onPress={saveValues} loading={busy === "save"} /></View>
        </Card>
      </Reveal>

      <Reveal delay={150}>
        <Card style={{ gap: spacing.sm }}>
          <T v="title3" c="negative">Erase all data</T>
          <T>Deletes every assignment, submission, grade, integrity decision, roster entry and ignored item, along with the stored PDFs, images and anything in the inbox folder. The settings above are kept. This cannot be undone.</T>
          <T v="footnote" c="inkSecondary">Export the grades and integrity reports you need first.</T>
          <View style={{ flexDirection: "row", flexWrap: "wrap", alignItems: "flex-end", gap: spacing.sm }}>
            <View style={{ width: 260 }}><Field value={erase} onChangeText={setErase} placeholder="Type erase to confirm" autoComplete="off" spellCheck={false} accessibilityLabel="Type erase to confirm" /></View>
            <Button variant="danger" label="Erase all data" disabled={erase.trim().toLowerCase() !== "erase"} loading={busy === "erase"} onPress={doErase} />
          </View>
        </Card>
      </Reveal>
    </Page>
  );
}
