'use client';

import { BaseEdge, EdgeLabelRenderer, getBezierPath, type EdgeProps } from '@xyflow/react';
import type { TrustFlowEdge } from '@/types/graph';

export function TrustEdge({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition, data, selected }: EdgeProps<TrustFlowEdge>): JSX.Element {
  const [path, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  const vulnerable = data?.isVulnerable ?? false;
  return <><BaseEdge path={path} className={selected ? 'trust-edge--selected' : vulnerable ? 'trust-edge trust-edge--vulnerable' : 'trust-edge'} /><EdgeLabelRenderer><div className={`pointer-events-none absolute -translate-x-1/2 -translate-y-1/2 rounded border px-2 py-1 text-[10px] font-semibold ${vulnerable ? 'border-rose-500/40 bg-rose-950/90 text-rose-200' : 'border-zinc-700 bg-zinc-900/90 text-zinc-400'}`} style={{ transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)` }}>{vulnerable ? data?.missingCondition ?? 'Missing trust condition' : data?.relation}</div></EdgeLabelRenderer></>;
}
