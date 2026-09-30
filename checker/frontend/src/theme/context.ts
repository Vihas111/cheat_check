import { createContext, useContext } from "react";

import { elevationByScheme, type ElevationLevel } from "./metrics";
import { palettes, type ColorScheme, type Palette } from "./palette";

/** What the user chose. "system" follows the OS. */
export type ThemePreference = ColorScheme | "system";

export type Theme = {
  scheme: ColorScheme;
  colors: Palette;
  shadow: (level: ElevationLevel) => { boxShadow: string };
  preference: ThemePreference;
  setPreference: (next: ThemePreference) => void;
};

export const ThemeContext = createContext<Theme>({
  scheme: "light",
  colors: palettes.light,
  shadow: (l) => ({ boxShadow: elevationByScheme.light[l] }),
  preference: "system",
  setPreference: () => {},
});

export const useTheme = () => useContext(ThemeContext);
export const useColors = () => useContext(ThemeContext).colors;
