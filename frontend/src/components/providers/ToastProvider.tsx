'use client';

import { createContext, useCallback, useContext, useState, type ReactNode } from 'react';

type ToastTone = 'success' | 'error' | 'info';
interface Toast { id: number; title: string; detail?: string; tone: ToastTone; }
interface ToastContextValue { showToast: (toast: Omit<Toast, 'id'>) => void; }
const ToastContext = createContext<ToastContextValue | null>(null);

export function ToastProvider({ children }: { children: ReactNode }): JSX.Element {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const showToast = useCallback((toast: Omit<Toast, 'id'>) => {
    const id = Date.now() + Math.floor(Math.random() * 10_000);
    setToasts((current) => [...current, { ...toast, id }]);
    window.setTimeout(() => setToasts((current) => current.filter((item) => item.id !== id)), 5_000);
  }, []);
  const toneClasses: Record<ToastTone, string> = { success: 'border-emerald-500/50 bg-emerald-950/95', error: 'border-rose-500/50 bg-rose-950/95', info: 'border-cyan-500/50 bg-zinc-900/95' };
  return <ToastContext.Provider value={{ showToast }}>{children}<div aria-live="polite" className="fixed right-4 top-4 z-50 w-[min(24rem,calc(100vw-2rem))] space-y-3">{toasts.map((toast) => <div key={toast.id} role="status" className={`rounded-xl border p-4 shadow-2xl backdrop-blur ${toneClasses[toast.tone]}`}><p className="font-semibold text-zinc-100">{toast.title}</p>{toast.detail && <p className="mt-1 text-sm text-zinc-300">{toast.detail}</p>}</div>)}</div></ToastContext.Provider>;
}

export function useToast(): ToastContextValue {
  const context = useContext(ToastContext);
  if (!context) throw new Error('useToast must be used within ToastProvider');
  return context;
}
