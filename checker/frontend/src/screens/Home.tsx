import { useState } from "react";
import { View } from "react-native";

import { api, useGet } from "../api/client";
import type { AssignmentCard } from "../api/types";
import { when } from "../meta";
import { useRouter } from "../router";
import { spacing, useColors } from "../theme";
import { AppBar, Loading, Page, useFeedback } from "../ui/chrome";
import { Button, Card, DateField, Dot, Field, Icon, Reveal, T, Tappable, web } from "../ui/primitives";

function NewAssignmentForm() {
  const { navigate } = useRouter();
  const { toast } = useFeedback();
  const [name, setName] = useState("");
  const [rubric, setRubric] = useState("");
  const [start, setStart] = useState("");
  const [deadline, setDeadline] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async () => {
    if (!name.trim()) return toast("Give the assignment a name.", { tone: "error" });
    setBusy(true);
    try {
      const r = await api.post<{ id: number; rubric_ok: boolean }>("/assignments", { name, rubric_text: rubric, start_at: start, deadline_at: deadline });
      if (!r.rubric_ok) toast("Assignment created. Could not read the rubric; fix it in Assignment setup.", { tone: "error" });
      navigate(`/a/${r.id}`);
    } catch (e) {
      toast((e as Error).message, { tone: "error" });
      setBusy(false);
    }
  };

  return (
    <Card style={{ gap: spacing.md }}>
      <Field label="Assignment name" value={name} onChangeText={setName} placeholder="HW2" autoFocus onSubmitEditing={create} />
      <Field
        label="Rubric" hint="Optional. One part per line, as Name | points. You can change it later."
        value={rubric} onChangeText={setRubric} rows={4} spellCheck={false}
        placeholder={"Part A: parsing | 10\nPart B: output table | 10\nPart C: graph and discussion | 5"}
      />
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: spacing.md }}>
        <View style={{ flex: 1, minWidth: 200 }}><DateField label="Opens" hint="optional" value={start} onChange={setStart} /></View>
        <View style={{ flex: 1, minWidth: 200 }}><DateField label="Deadline" hint="optional" value={deadline} onChange={setDeadline} /></View>
      </View>
      <T v="footnote" c="inkSecondary">With dates, screenshots showing a clock or date outside this window are pointed out.</T>
      <View style={{ flexDirection: "row" }}><Button variant="primary" label="Create assignment" onPress={create} loading={busy} /></View>
    </Card>
  );
}

export function NewAssignment() {
  const bar = <AppBar title="New assignment" crumbs={[{ label: "Assignments", to: "/" }]} />;
  return <Page bar={bar} narrow><Reveal><NewAssignmentForm /></Reveal></Page>;
}

export function Home() {
  const c = useColors();
  const { navigate } = useRouter();
  const { data, error, reload } = useGet<AssignmentCard[]>("/assignments");

  if (!data) return <Page bar={<AppBar title="Grader" />}><Loading error={error} retry={reload} /></Page>;

  const bar = (
    <AppBar
      title="Assignments"
      actions={<><Button label="Settings" onPress={() => navigate("/settings")} /><Button variant="primary" icon="plus" label="New assignment" onPress={() => navigate("/new")} /></>}
    />
  );

  if (!data.length) {
    return (
      <Page bar={<AppBar title="Grader" actions={<Button label="Settings" onPress={() => navigate("/settings")} />} />} narrow>
        <Reveal>
          <View style={{ gap: spacing.sm, marginBottom: spacing.md }}>
            <T v="display">Grade PDF submissions on this computer</T>
            <T c="inkSecondary">
              Open a submission, use the marking panel to enter marks by rubric, write feedback and release grades when you are ready. The built-in similarity check points out screenshots, typed answers, tables and graphs that also appear in other submissions. It only makes suggestions: you decide what, if anything, follows.
            </T>
            <View style={{ gap: 4, marginTop: spacing.sm }}>
              {["Name the assignment and write its rubric.", "Drop in the PDFs. Each one opens for grading right away.", "Work through the list: mark, add feedback, release."].map((s, i) => (
                <T key={i} c="inkSecondary">{i + 1}.  {s}</T>
              ))}
            </View>
          </View>
        </Reveal>
        <Reveal delay={80}><NewAssignmentForm /></Reveal>
      </Page>
    );
  }

  return (
    <Page bar={bar}>
      <Card pad={0}>
        {data.map((a, i) => (
          <Reveal key={a.id} delay={i * 40}>
            <Tappable onPress={() => navigate(`/a/${a.id}`)} label={a.name} style={{ borderTopWidth: i ? 1 : 0, borderTopColor: c.hairline, borderTopLeftRadius: i ? 0 : 15, borderTopRightRadius: i ? 0 : 15, borderBottomLeftRadius: i === data.length - 1 ? 15 : 0, borderBottomRightRadius: i === data.length - 1 ? 15 : 0 }}>
              <View style={{ flexDirection: "row", alignItems: "center", gap: spacing.md, padding: spacing.lg, minHeight: 68 }}>
                <View style={{ flex: 1, minWidth: 0 }}>
                  <T v="title3" numberOfLines={1}>{a.name}</T>
                  <T v="footnote" c="inkSecondary">
                    {a.total} {a.total === 1 ? "submission" : "submissions"}{a.deadline_at ? `  ·  Due ${when(a.deadline_at)}` : ""}
                  </T>
                </View>
                {a.waiting ? (
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
                    <Dot color={c.warning} /><T v="footnote" c="warning" style={{ fontWeight: "600" }}>{a.waiting} to check</T>
                  </View>
                ) : null}
                <T v="footnote" c="inkSecondary">{a.released} of {a.total} released</T>
                <Icon name="right" color={c.inkTertiary} />
              </View>
            </Tappable>
          </Reveal>
        ))}
      </Card>
    </Page>
  );
}
