import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { useColorScheme } from "react-native";

import { ThemeContext, type ThemePreference } from "./context";
import { elevationByScheme, fontFamily } from "./metrics";
import { palettes } from "./palette";

// Same key the old server-rendered pages used, so a saved choice carries over.
const KEY = "theme";

function stored(): ThemePreference {
  const v = localStorage.getItem(KEY);
  return v === "light" || v === "dark" ? v : "system";
}

export function ThemeProvider({ children }: { children: ReactNode }) {
  const system = useColorScheme() === "dark" ? "dark" : "light";
  const [preference, setPref] = useState<ThemePreference>(stored);
  const scheme = preference === "system" ? system : preference;
  const colors = palettes[scheme];

  // Page background and native controls (scrollbars, date pickers) follow the scheme.
  useEffect(() => {
    document.body.style.backgroundColor = colors.canvas;
    document.body.style.fontFamily = fontFamily;
    document.documentElement.style.colorScheme = scheme;
  }, [scheme, colors]);

  const setPreference = useCallback((next: ThemePreference) => {
    setPref(next);
    if (next === "system") localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, next);
  }, []);

  const value = useMemo(
    () => ({ scheme, colors, preference, setPreference, shadow: (l: keyof typeof elevationByScheme.light) => ({ boxShadow: elevationByScheme[scheme][l] }) }),
    [scheme, colors, preference, setPreference],
  );
  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}
