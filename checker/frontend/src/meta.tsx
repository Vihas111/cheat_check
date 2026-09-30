import { createContext, useContext, type ReactNode } from "react";

import { useGet } from "./api/client";
import type { Meta } from "./api/types";

const empty: Meta = { labels: { tier: {}, decision: {}, verify: {}, flag: {} }, pipeline_version: 0 };
const MetaContext = createContext<Meta>(empty);

/** The words the server uses for tiers, decisions and flags, so the screens never re-type them. */
export function MetaProvider({ children }: { children: ReactNode }) {
  const { data } = useGet<Meta>("/meta");
  return <MetaContext.Provider value={data ?? empty}>{children}</MetaContext.Provider>;
}

export const useMeta = () => useContext(MetaContext).labels;

export const GRADE_LABEL: Record<string, string> = { none: "Not graded", draft: "Draft", released: "Released" };

export const fmt = (v: number | null | undefined) => (v === null || v === undefined ? "" : String(+v.toFixed(2)));
export const pct = (v: number | null | undefined) => (v === null || v === undefined ? "–" : `${Math.round(v * 100)}%`);
export const when = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";
