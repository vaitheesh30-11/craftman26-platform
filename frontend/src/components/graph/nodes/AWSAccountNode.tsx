'use client';

import { Building2, Network } from 'lucide-react';
import { type NodeProps } from '@xyflow/react';
import type { TrustFlowNode } from '@/types/graph';

export function AWSAccountNode({ data, selected }: NodeProps<TrustFlowNode>): JSX.Element {
  const Icon = data.nodeKind === 'OU' ? Network : Building2;
  return <div className={`min-w-52 rounded-xl border bg-zinc-900/85 p-4 shadow-xl backdrop-blur transition-all duration-200 ${selected ? 'border-cyan-400 ring-2 ring-cyan-400/30' : 'border-cyan-500/40'} ${data.isCompromised ? 'shadow-rose-950/70' : 'shadow-black/30'}`}><div className="flex items-center gap-3"><span className="grid h-9 w-9 place-items-center rounded-lg bg-cyan-500/15 text-cyan-300"><Icon size={18} /></span><div className="min-w-0"><p className="text-[10px] font-semibold uppercase tracking-[0.16em] text-cyan-400">{data.nodeKind}</p><p className="truncate text-sm font-semibold text-zinc-100">{data.label}</p></div></div>{data.isCompromised && <p className="mt-3 rounded bg-rose-500/10 px-2 py-1 text-xs font-medium text-rose-300">Attack path reaches this account</p>}</div>;
}
