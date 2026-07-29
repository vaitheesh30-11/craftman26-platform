'use client';

import { AppHeader } from './AppHeader';
import { Sidebar } from './Sidebar';

interface LayoutShellProps {
  children: React.ReactNode;
}

export function LayoutShell({ children }: LayoutShellProps): JSX.Element {
  return (
    <div className="min-h-screen bg-zinc-950">
      <AppHeader />
      <div className="flex">
        <Sidebar />
        <main className="min-w-0 flex-1">
          {children}
        </main>
      </div>
    </div>
  );
}
