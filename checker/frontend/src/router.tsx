import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

// A tiny history-API router: the server serves the same page for every URL, so links, reloads and the
// back button all keep working. Screens are matched by pattern and animated in by <Stage>.

const ROUTES: [RegExp, string, string[]][] = [
  [/^\/$/, "home", []],
  [/^\/new$/, "new", []],
  [/^\/settings$/, "settings", []],
  [/^\/a\/(\d+)$/, "assignment", ["aid"]],
  [/^\/a\/(\d+)\/setup$/, "setup", ["aid"]],
  [/^\/a\/(\d+)\/clusters$/, "clusters", ["aid"]],
  [/^\/a\/(\d+)\/calibrate$/, "calibrate", ["aid"]],
  [/^\/s\/(\d+)$/, "submission", ["sid"]],
  [/^\/m\/(\d+)$/, "compare", ["mid"]],
  [/^\/i\/(\d+)$/, "item", ["iid"]],
];

export type Route = { name: string; params: Record<string, string>; path: string; query: URLSearchParams };

function match(url: URL): Route {
  for (const [re, name, keys] of ROUTES) {
    const m = re.exec(url.pathname);
    if (m) return { name, params: Object.fromEntries(keys.map((k, i) => [k, m[i + 1]])), path: url.pathname, query: url.searchParams };
  }
  return { name: "missing", params: {}, path: url.pathname, query: url.searchParams };
}

type Nav = {
  route: Route;
  /** +1 when the last move went deeper, -1 when it went back; picks the slide direction. */
  direction: number;
  navigate: (to: string, opts?: { replace?: boolean }) => void;
  back: (fallback: string) => void;
};

const RouterContext = createContext<Nav>(null as unknown as Nav);
export const useRouter = () => useContext(RouterContext);

export function RouterProvider({ children }: { children: ReactNode }) {
  const [href, setHref] = useState(() => location.pathname + location.search);
  const [direction, setDirection] = useState(1);

  const go = useCallback((to: string, replace: boolean) => {
    const path = to.split("?")[0];
    setDirection(path.length >= location.pathname.length ? 1 : -1);
    if (replace) history.replaceState(null, "", to);
    else history.pushState(null, "", to);
    if (path !== location.pathname) window.scrollTo(0, 0);
    setHref(to);
  }, []);

  useEffect(() => {
    const onPop = () => {
      setDirection(-1);
      setHref(location.pathname + location.search);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const value = useMemo<Nav>(
    () => ({
      route: match(new URL(href, location.origin)),
      direction,
      navigate: (to, opts) => go(to, !!opts?.replace),
      back: (fallback) => (history.length > 1 ? history.back() : go(fallback, false)),
    }),
    [href, direction, go],
  );

  return <RouterContext.Provider value={value}>{children}</RouterContext.Provider>;
}

export const FILTER_KEYS = ["grade", "status", "tier", "q"] as const;

/** The dashboard filters carried in the address ("grade=none&status=clear"), so the grader walks only the filtered list. */
export function useFilterQs(): string {
  const { route } = useRouter();
  const q = new URLSearchParams();
  for (const k of FILTER_KEYS) {
    const v = route.query.get(k);
    if (v) q.set(k, v);
  }
  return q.toString();
}

/** A submission address that keeps the filters; extra is e.g. "tab=integrity". */
export const subPath = (id: number | string, qs: string, extra = "") => {
  const s = [qs, extra].filter(Boolean).join("&");
  return `/s/${id}${s ? "?" + s : ""}`;
};

/** Update only the query string (filters, tabs) without adding a history entry per keystroke. */
export function useQuery() {
  const { route, navigate } = useRouter();
  const set = useCallback(
    (patch: Record<string, string>, replace = true) => {
      const q = new URLSearchParams(route.query);
      for (const [k, v] of Object.entries(patch)) {
        if (v) q.set(k, v);
        else q.delete(k);
      }
      const s = q.toString();
      navigate(route.path + (s ? "?" + s : ""), { replace });
    },
    [route, navigate],
  );
  return [route.query, set] as const;
}
