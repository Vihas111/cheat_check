export type Criterion = { name: string; points: number };
export type Assignment = {
  id: number; name: string; notes: string | null; max_score: number; start_at: string | null; deadline_at: string | null;
  rubric: Criterion[]; has_rubric: boolean; rubric_text: string;
};
export type AssignmentCard = Assignment & { total: number; released: number; waiting: number };
export type Student = { student_id: string; name: string | null } | null;
export type Row = {
  id: number; filename: string; student: Student; gradable: boolean; is_seed: boolean; is_reference: boolean;
  status: string; mark: { total: number | null; status: string } | null; verify: string | null; decision: string | null;
  tier: string | null; coverage: number | null; top: { filename: string } | null;
};
export type Dashboard = {
  assignment: Assignment; rows: Row[]; total: number; counts: { queued: number; processing: number; done: number; failed: number };
  verify: Record<string, number>; grades: Record<string, number>; failed: { filename: string; error: string }[];
  wl_count: number; has_roster: boolean; rescanning: boolean; compared: { seed: number; reference: number }; inbox: string;
};
export type Meta = {
  labels: { tier: Record<string, string>; decision: Record<string, string>; verify: Record<string, string>; flag: Record<string, string> };
  pipeline_version: number;
};
export type Source = { submission_id: number; filename: string; share: number; items: number; is_reference?: boolean };
export type Item = {
  id: number; page: number; label: string; weight: number | null; df: number | null; thumb: string | null; text: string; lines: string[];
  matched: boolean; matches: { id: number; filename: string; submission_id: number; what: string }[];
};
export type Submission = {
  id: number; filename: string; page_count: number; status: string; is_seed: boolean; is_reference: boolean; error: string;
  assignment: { id: number; name: string; max_score: number; rubric: Criterion[] };
  student: Student; verify: string | null;
  nav: { pos: number; count: number; prev: number | null; next: number | null; next_ungraded: number | null; next_flagged: number | null; filtered: boolean };
  report: { tier: string | null; reasons: string[]; coverage: number | null; population: number | null; by_source: Source[] };
  flags: { type: string; severity: string; summary: string; help: string; evidence: unknown }[];
  reviews: { status: string; note: string | null; ts: string; suggested: string | null }[];
  mark: { scores: Record<string, number>; total: number | null; feedback: string; status: string; updated_at: string } | null;
  items: Item[]; meta: { heads: string[]; rows: string[][] };
};
export type Panel = {
  item_id: number; lines: string[]; submission_id: number; filename: string; label: string; thumb: string | null; text_title: string; chunks: [string, boolean][];
};
export type ItemMatch = {
  match_id: number; submission_id: number; filename: string; student: { student_id: string; name: string | null } | null;
  item_id: number; page: number; label: string; thumb: string | null; kind: string; what: string; why: string; shared: string[]; lines: string[];
};
export type ItemPage = {
  item: { id: number; page: number; label: string; thumb: string | null; lines: string[]; kinds: string[]; weight: number | null; df: number | null };
  submission: { id: number; filename: string; student: { student_id: string; name: string | null } | null };
  assignment: { id: number; name: string };
  matches: ItemMatch[];
};
export type Compare = {
  id: number; kind: string; summary: string; assignment: { id: number; name: string }; siblings: number[];
  a: Panel; b: Panel; overlay: string | null;
};
export type Groups = {
  assignment: { id: number; name: string };
  groups: { hub: number; members: { id: number; filename: string; tier: string | null }[]; edges: { a: string; b: string; items: number; weight: number }[] }[];
};
export type Chart = {
  title: string; hist: { lo: number; n: number; h: number }[]; cut: number | null; current: number; setting: string; fmt: string;
};
export type Calibration = { assignment: { id: number; name: string }; n: number; charts: Chart[] };
export type Settings = {
  fields: { name: string; value: string | number; help: string; type: string }[]; roster: number; engines: string[];
  ignored: { kind: string; scope: string | null; reason: string | null; pieces: number }[];
};
