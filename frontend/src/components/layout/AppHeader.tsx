'use client';

import { useSessionStore } from '@/store/useSessionStore';
import { Shield, Menu, X } from 'lucide-react';

export function AppHeader(): JSX.Element {
  const { isSidebarOpen, setSidebarOpen } = useSessionStore();
  return (
    <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-zinc-800/80 bg-zinc-950/90 px-4 backdrop-blur-xl shadow-sm shadow-black/10">
      <div className="flex items-center gap-3">
        <button
          aria-label={isSidebarOpen ? 'Close navigation' : 'Open navigation'}
          className="grid h-9 w-9 place-items-center rounded-lg text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"
          onClick={() => setSidebarOpen(!isSidebarOpen)}
        >
          {isSidebarOpen ? <X size={18} /> : <Menu size={18} />}
        </button>
        <div className="flex items-center gap-2.5">
          <span className="grid h-8 w-8 place-items-center rounded-lg bg-cyan-500/15">
            <Shield size={18} className="text-cyan-400" />
          </span>
          <span className="text-lg font-semibold tracking-tight text-zinc-100">
            Sentinel<span className="text-cyan-400">-IQ</span>
          </span>
        </div>
      </div>
      <div className="flex items-center gap-4">
        <span className="hidden text-sm text-zinc-500 sm:block">Governance command center</span>
        <span className="hidden h-5 w-px bg-zinc-800 sm:block" />
        <div className="flex items-center gap-2 rounded-lg border border-zinc-800 bg-zinc-900/50 px-3 py-1.5">
          <span className="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-xs font-medium text-emerald-300">Live</span>
        </div>
      </div>
    </header>
  );
}