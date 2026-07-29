import { cn } from '@/lib/utils';

export function getPolicyByteLength(value: string): number {
  try { return new TextEncoder().encode(JSON.stringify(JSON.parse(value))).length; } catch { return new TextEncoder().encode(value).length; }
}

export function ByteQuotaGauge({ value }: { value: string }): JSX.Element {
  const bytes = getPolicyByteLength(value);
  const ratio = Math.min((bytes / 10_240) * 100, 100);
  const state = bytes >= 10_240 ? { label: 'Quota exceeded', bar: 'bg-rose-500', text: 'text-rose-300' } : bytes > 8_000 ? { label: 'Approaching quota', bar: 'bg-amber-400', text: 'text-amber-300' } : { label: 'Within quota', bar: 'bg-emerald-400', text: 'text-emerald-300' };
  return <div className="rounded-b-xl border-x border-b border-zinc-800 bg-zinc-950/70 px-4 py-3"><div className="flex items-center justify-between gap-3 text-xs"><span className={cn('font-semibold', state.text)}>{state.label}</span><span className="font-mono text-zinc-400">{bytes.toLocaleString()} / 10,240 bytes</span></div><div className="mt-2 h-1.5 overflow-hidden rounded-full bg-zinc-800"><div className={cn('h-full rounded-full transition-all duration-300', state.bar)} style={{ width: `${ratio}%` }} /></div></div>;
}
