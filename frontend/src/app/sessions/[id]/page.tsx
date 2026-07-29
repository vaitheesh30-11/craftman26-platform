'use client';

import { useParams } from 'next/navigation';
import { useCallback, useState } from 'react';
import { useSessionStore, type WorkspaceTab } from '@/store/useSessionStore';
import { useWebSocketStream } from '@/hooks/useWebSocketStream';
import { AgentDebateFeed } from '@/components/feed/AgentDebateFeed';
import { StreamStatusBadge } from '@/components/feed/StreamStatusBadge';
import { ExecutionMetricsBar } from '@/components/telemetry/ExecutionMetricsBar';
import type { ExecutionMetrics, ProofStatusUpdatedEvent, StreamEvent } from '@/types/stream';
import { useGetSessionDetail } from '@/hooks/api/useSessionApi';
import { ASTDiffEditor } from '@/components/editor/ASTDiffEditor';
import { HITLControlPanel } from '@/components/workspace/HITLControlPanel';
import { NeptuneTopologyCanvas } from '@/components/graph/NeptuneTopologyCanvas';
import type { NeptunePath } from '@/types/graph';

const tabs: { id: WorkspaceTab; label: string }[] = [{ id: 'DIFF_VIEWER', label: 'Policy diff' }, { id: 'TOPOLOGY_MAP', label: 'Topology map' }, { id: 'DEBATE_LOG', label: 'Debate log' }];

function isNeptunePath(value: unknown): value is NeptunePath {
  if (typeof value !== 'object' || value === null) return false;
  const path = value as Partial<NeptunePath>;
  return typeof path.source === 'string' || typeof path.target === 'string' || (typeof path.source === 'object' && path.source !== null && typeof path.target === 'object' && path.target !== null);
}

export default function SessionWorkspacePage(): JSX.Element {
  const params = useParams<{ id: string }>();
  const { activeWorkspaceTab, setWorkspaceTab } = useSessionStore();
  const stream = useWebSocketStream(params.id, true);
  const sessionQuery = useGetSessionDetail(params.id);
  const [editedPolicy, setEditedPolicy] = useState<string | null>(null);
  const [isJsonValid, setIsJsonValid] = useState(true);
  const proof = [...stream.latestEvents].reverse().find((event): event is ProofStatusUpdatedEvent => event.event_type === 'PROOF_STATUS_UPDATED') ?? null;
  const policyEvent = [...stream.latestEvents].reverse().find((event): event is StreamEvent & { byte_size: number } => event.event_type === 'POLICY_AST_UPDATED' && 'byte_size' in event);
  const metrics: ExecutionMetrics = { iteration: Math.min(3, Math.max(1, stream.latestEvents.filter((event) => event.event_type === 'AGENT_TURN_EMITTED').length)), maxIterations: 3, tokenBurnRate: 1240, policyBytes: policyEvent?.byte_size ?? 7820, zelkovaStatus: proof?.zelkova_status ?? sessionQuery.data?.zelkovaStatus ?? 'UNVERIFIED', alertCount: proof?.counter_examples.length ?? 0, blastRadiusScore: proof?.blast_radius_score ?? sessionQuery.data?.blastRadiusScore ?? 0.18 };
  const originalPolicy = sessionQuery.data?.baselinePolicyJson ?? '{}';
  const proposedPolicy = sessionQuery.data?.workingPolicyJson ?? '{}';
  const targetPolicy = editedPolicy ?? proposedPolicy;
  const isDirty = editedPolicy !== null && editedPolicy !== proposedPolicy;
  const graphTelemetry = sessionQuery.data?.problemTelemetry.graph_paths;
  const topologyPaths = Array.isArray(graphTelemetry) && graphTelemetry.every(isNeptunePath) ? graphTelemetry : undefined;
  const onPolicyChange = useCallback((value: string, valid: boolean): void => { setEditedPolicy(value); setIsJsonValid(valid); }, []);
  let policyView: JSX.Element;
  if (sessionQuery.isLoading) {
    policyView = <section className="grid min-h-[30rem] place-items-center rounded-xl border border-zinc-800 bg-zinc-900/60 text-sm text-zinc-400">Loading governed policy workspace…</section>;
  } else if (sessionQuery.isError) {
    policyView = <section role="alert" className="rounded-xl border border-rose-500/40 bg-rose-500/10 p-6 text-rose-200"><h2 className="font-semibold">Unable to load this session</h2><p className="mt-2 text-sm">Refresh the workspace to retry the policy review.</p></section>;
  } else if (!sessionQuery.data) {
    policyView = <section className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-6 text-zinc-400">No policy payload is available for this session.</section>;
  } else {
    policyView = <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_21rem]"><ASTDiffEditor baselinePolicyJson={originalPolicy} workingPolicyJson={proposedPolicy} onTargetPolicyChange={onPolicyChange} /><HITLControlPanel sessionId={sessionQuery.data.sessionId} targetPolicyJson={targetPolicy} isJsonValid={isJsonValid} isDirty={isDirty} zelkovaStatus={metrics.zelkovaStatus} onProofComplete={() => undefined} /></div>;
  }
  return <div className="p-4 md:p-6"><div className="flex flex-wrap items-start justify-between gap-3"><div><p className="text-sm text-zinc-500">Session {params.id}</p><h1 className="mt-1 text-2xl font-semibold text-zinc-100">Human-in-the-loop workspace</h1></div><StreamStatusBadge state={stream.connectionState} pingLatencyMs={stream.pingLatencyMs} /></div><div className="mt-6"><ExecutionMetricsBar metrics={metrics} /></div><div className="mt-6 flex gap-1 overflow-x-auto border-b border-zinc-800">{tabs.map((tab, index) => <button key={tab.id} onClick={() => setWorkspaceTab(tab.id)} className={`relative whitespace-nowrap px-4 py-3 text-sm font-medium transition-colors ${activeWorkspaceTab === tab.id ? 'text-cyan-300' : 'text-zinc-500 hover:text-zinc-200'}`}>{tab.label}{activeWorkspaceTab === tab.id && <span className="absolute bottom-0 left-2 right-2 h-0.5 rounded-full bg-cyan-400" />}</button>)}</div><div className="mt-6">{activeWorkspaceTab === 'DEBATE_LOG' ? <AgentDebateFeed events={stream.latestEvents} /> : activeWorkspaceTab === 'DIFF_VIEWER' ? policyView : <NeptuneTopologyCanvas paths={topologyPaths} isLoading={sessionQuery.isLoading} error={sessionQuery.isError ? 'The session topology could not be loaded.' : null} />}</div></div>;
}
