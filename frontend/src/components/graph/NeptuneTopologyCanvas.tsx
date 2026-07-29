'use client';

import '@xyflow/react/dist/style.css';
import { useMemo, useState } from 'react';
import { Background, BackgroundVariant, Controls, MiniMap, ReactFlow, ReactFlowProvider, type NodeMouseHandler, type NodeTypes, type EdgeTypes, type Node } from '@xyflow/react';
import { ChevronRight, ShieldAlert, X, FileText } from 'lucide-react';
import { useGraphLayout } from '@/hooks/graph/useGraphLayout';
import { mockTrustPaths, useNeptuneParser } from '@/hooks/graph/useNeptuneParser';
import type { NeptunePath, TrustFlowNode } from '@/types/graph';
import { AWSAccountNode } from './nodes/AWSAccountNode';
import { IAMRoleNode } from './nodes/IAMRoleNode';
import { TrustEdge } from './edges/TrustEdge';

const nodeTypes: NodeTypes = { accountNode: AWSAccountNode, iamRoleNode: IAMRoleNode };
const edgeTypes: EdgeTypes = { trustEdge: TrustEdge };

interface NeptuneTopologyCanvasProps { paths?: NeptunePath[]; isLoading?: boolean; error?: string | null; }

function TopologyCanvas({ paths = mockTrustPaths, isLoading = false, error = null }: NeptuneTopologyCanvasProps): JSX.Element {
  const [maxDepth, setMaxDepth] = useState(2);
  const [selectedNode, setSelectedNode] = useState<TrustFlowNode | null>(null);
  const { nodes: parsedNodes, edges } = useNeptuneParser(paths, maxDepth);
  const nodes = useGraphLayout(parsedNodes, edges);
  const compromisedCount = useMemo(() => nodes.filter((node) => node.data.isCompromised).length, [nodes]);
  const onNodeClick: NodeMouseHandler = (_, node: Node) => setSelectedNode(node as TrustFlowNode);
  if (isLoading) return <section className="grid h-[38rem] place-items-center rounded-2xl border border-zinc-800 bg-zinc-900/60 text-sm text-zinc-400">Mapping trust relationships…</section>;
  if (error) return <section role="alert" className="rounded-2xl border border-rose-500/40 bg-rose-500/10 p-6 text-rose-200"><h2 className="font-semibold">Unable to map topology</h2><p className="mt-2 text-sm">{error}</p></section>;
  if (nodes.length === 0) return <section className="rounded-2xl border border-zinc-800 bg-zinc-900/60 p-8 text-center"><h2 className="font-semibold text-zinc-100">No trust relationships found</h2><p className="mt-2 text-sm text-zinc-500">This session does not contain any Neptune path data.</p></section>;
  return <section aria-label="Neptune trust topology" className="relative h-[38rem] overflow-hidden rounded-2xl border border-zinc-800 bg-zinc-950 shadow-2xl shadow-black/30"><div className="absolute left-4 top-4 z-10 max-w-sm rounded-xl border border-zinc-700 bg-zinc-900/90 p-4 backdrop-blur"><div className="flex items-center gap-2"><ShieldAlert size={17} className="text-rose-400" /><h2 className="font-semibold text-zinc-100">Cross-account trust topology</h2></div><p className="mt-1 text-xs leading-5 text-zinc-400">Highlighted paths expose missing trust conditions and lateral movement risk.</p><label className="mt-3 flex items-center justify-between gap-4 text-xs text-zinc-300">Visible relationship depth<select value={maxDepth} onChange={(event) => { setMaxDepth(Number(event.target.value)); setSelectedNode(null); }} className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-zinc-100"><option value={1}>1 hop</option><option value={2}>2 hops</option><option value={3}>3 hops</option></select></label></div>{compromisedCount > 0 && <div className="absolute right-4 top-4 z-10 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-200"><span className="font-semibold">{compromisedCount}</span> compromised node{compromisedCount !== 1 ? 's' : ''}</div>}<ReactFlow nodes={nodes} edges={edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes} fitView fitViewOptions={{ padding: 0.25 }} minZoom={0.35} maxZoom={1.6} onNodeClick={onNodeClick} nodesDraggable={false} nodesConnectable={false}><Background gap={20} size={1.5} color="#27272a" variant={BackgroundVariant.Dots} /><MiniMap position="bottom-right" zoomable pannable nodeColor={(node) => (node.data as { isCompromised?: boolean }).isCompromised ? '#f43f5e' : '#22d3ee'} maskColor="rgba(9,9,11,0.75)" /><Controls position="bottom-left" showInteractive={false} /></ReactFlow>{selectedNode && <aside aria-label="Selected trust node details" className="absolute inset-y-0 right-0 z-20 w-full max-w-md overflow-y-auto border-l border-zinc-700 bg-zinc-950/95 p-5 shadow-2xl backdrop-blur-xl transform transition-transform duration-300 ease-out"><div className="flex items-center justify-between gap-3"><div className="flex items-center gap-2"><span className="grid h-8 w-8 place-items-center rounded-lg bg-zinc-800"><ShieldAlert size={16} className="text-zinc-300" /></span><div><p className="text-xs font-medium text-zinc-400">Selected node</p><p className="text-sm font-semibold text-zinc-100">{selectedNode.data.label}</p></div></div><button onClick={() => setSelectedNode(null)} className="grid h-8 w-8 place-items-center rounded-lg text-zinc-400 transition hover:bg-zinc-800 hover:text-zinc-100"><X size={16} /></button></div><div className="mt-4 space-y-3"><div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3"><p className="text-xs text-zinc-500">Node type</p><p className="mt-1 text-sm text-zinc-200">{selectedNode.data.nodeKind.replace('_', ' ')}</p></div>{selectedNode.data.isCompromised && <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3"><p className="text-xs text-rose-400">Warning</p><p className="mt-1 text-sm text-rose-200">This node is part of a vulnerable trust path.</p></div>}<div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-3"><p className="text-xs text-zinc-500">Attached policies</p><div className="mt-2 space-y-2">{selectedNode.data.policies?.map((policy, index) => <pre key={index} className="overflow-x-auto rounded bg-zinc-950 p-2 text-xs leading-5 text-zinc-300">{policy}</pre>) ?? <p className="text-xs text-zinc-500">No policy data attached.</p>}</div></div></div></aside>}</section>;
}

export function NeptuneTopologyCanvas(props: NeptuneTopologyCanvasProps): JSX.Element { return <ReactFlowProvider><TopologyCanvas {...props} /></ReactFlowProvider>; }
