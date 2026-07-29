'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useSessionStore } from '@/store/useSessionStore';
import { LayoutDashboard, Activity, Shield, Settings } from 'lucide-react';

const navItems = [
  { href: '/dashboard', label: 'Sessions', icon: LayoutDashboard },
  { href: '/', label: 'Activity', icon: Activity },
  { href: '/login', label: 'Settings', icon: Settings },
];

export function Sidebar(): JSX.Element | null {
  const isSidebarOpen = useSessionStore((state) => state.isSidebarOpen);
  const pathname = usePathname();

  if (!isSidebarOpen) return null;

  return (
    <>
      <div
        className="fixed inset-0 z-20 bg-black/60 backdrop-blur-sm lg:hidden"
        onClick={() => useSessionStore.getState().setSidebarOpen(false)}
      />
      <aside className="fixed inset-y-0 left-0 z-30 w-60 shrink-0 transform animate-slide-in-from-left border-r border-zinc-800/80 bg-zinc-950/95 p-4 backdrop-blur-xl lg:relative lg:z-auto lg:transform-none">
        <nav aria-label="Primary navigation" className="space-y-1">
          {navItems.map((item) => {
            const isActive = pathname === item.href || (item.href !== '/' && pathname.startsWith(item.href));
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200 ${
                  isActive
                    ? 'bg-cyan-500/10 text-cyan-300 border border-cyan-500/20 shadow-sm shadow-cyan-500/5'
                    : 'text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-200 border border-transparent'
                }`}
              >
                <item.icon size={17} className={isActive ? 'text-cyan-400' : 'text-zinc-500'} />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="mt-8 rounded-lg border border-zinc-800 bg-zinc-900/50 p-3">
          <div className="flex items-center gap-2">
            <Shield size={14} className="text-cyan-400" />
            <span className="text-xs font-medium text-zinc-300">System status</span>
          </div>
          <div className="mt-2 flex items-center gap-2">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse-slow" />
            <span className="text-xs text-zinc-500">All systems nominal</span>
          </div>
        </div>
      </aside>
    </>
  );
}
