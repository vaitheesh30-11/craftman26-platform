'use client';

import { KeyRound, ShieldAlert, Store } from 'lucide-react';
import { type NodeProps } from '@xyflow/react';
import type { TrustFlowNode } from '@/types/graph';

export function IAMRoleNode({ data, selected }: NodeProps<TrustFlowNode>): JSX.Element {
  const isVendor = data.nodeKind === 'EXTERNAL_VENDOR';
  const Icon = data.isCompromised ? ShieldAlert : isVendor ? Store : KeyRound;
  const color = data.isCompromised ? 'rose' : isVendor ? 'amber' : 'violet';
  const palette = { rose: 'border-rose-500/60 bg-rose-500/10 text-rose-300', amber: 'border-amber-500/50 bg-amber-500/10 text-amber-300', violet: 'border-violet-500/50 bg-violet-500/10 text-violet-300' }[color];
  return <div className={`min-w-52 rounded-xl border bg-zinc-900/85 p-4 shadow-xl backdrop-blur transition-all duration-200 ${selected ? 'ring-2 ring-zinc-100/30' : ''} ${palette}`}><div className="flex items-center gap-3"><span className={`grid h-9 w-9 place-items-center rounded-lg ${palette}`}><Icon size={18} /></span><div className="min-w-0"><p className="text-[10px] font-semibold uppercase tracking-[0.16em] opacity-80">{data.nodeKind.replace('_', ' ')}</p><p className="truncate text-sm font-semibold text-zinc-100">{data.label}</p></div></div><p className="mt-3 text-xs text-zinc-400">{data.isCompromised ? 'Compromised trust boundary' : 'Trust relationship node'}</p></div>;
}
