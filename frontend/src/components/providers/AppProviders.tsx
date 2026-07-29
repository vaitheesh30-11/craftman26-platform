'use client';

import type { ReactNode } from 'react';
import { AuthProvider } from './AuthProvider';
import { QueryProvider } from './QueryProvider';
import { ThemeProvider } from './ThemeProvider';
import { ToastProvider } from './ToastProvider';

export function AppProviders({ children }: { children: ReactNode }): JSX.Element {
  return <ThemeProvider><AuthProvider><QueryProvider><ToastProvider>{children}</ToastProvider></QueryProvider></AuthProvider></ThemeProvider>;
}
