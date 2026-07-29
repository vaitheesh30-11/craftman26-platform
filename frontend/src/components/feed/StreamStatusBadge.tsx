import { cn } from '@/lib/utils';
import type { ConnectionState } from '@/types/stream';

const stateStyles: Record<ConnectionState, string> = { LIVE: 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300', CONNECTING: 'border-amber-500/40 bg-amber-500/10 text-amber-300', RECONNECTING: 'border-violet-500/40 bg-violet-500/10 text-violet-300', DISCONNECTED: 'border-zinc-700 bg-zinc-800 text-zinc-400' };

export function StreamStatusBadge({ state, pingLatencyMs }: { state: ConnectionState; pingLatencyMs: number | null }): JSX.Element {
  return <span className={cn('inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-semibold', stateStyles[state])}><span className={cn('h-2 w-2 rounded-full', state === 'LIVE' ? 'animate-pulse bg-emerald-400' : state === 'DISCONNECTED' ? 'bg-zinc-500' : 'animate-ping bg-current')} />{state}{state === 'LIVE' && pingLatencyMs !== null ? ` · ${pingLatencyMs}ms` : ''}</span>;
}
