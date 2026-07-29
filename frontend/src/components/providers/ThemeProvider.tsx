'use client';

import { createContext, useContext, useEffect, type ReactNode } from 'react';

type Theme = 'dark';
const ThemeContext = createContext<Theme>('dark');

/** Sentinel-IQ is intentionally dark-only to preserve its SOC visual contrast. */
export function ThemeProvider({ children }: { children: ReactNode }): JSX.Element {
  useEffect(() => { document.documentElement.classList.add('dark'); }, []);
  return <ThemeContext.Provider value="dark">{children}</ThemeContext.Provider>;
}

export function useTheme(): Theme { return useContext(ThemeContext); }
