'use client';

import { useQuery } from '@tanstack/react-query';
import { Shield, AlertTriangle, CheckCircle, Clock, ArrowRight, Activity } from 'lucide-react';
import Link from 'next/link';
import type { SessionSummary } from '@/types/dto';

const mockSessions: SessionSummary[] = [
  { id: '1', sessionId: 'ses-7f43', activeProblemId: 'SCP-2', status: 'AWAITING_HITL', targetArn: 'arn:aws:organizations::123456789012:policy/o-root/scp-guardrails', zelkovaStatus: 'PASS', blastRadiusScore: 0.18, createdAt: '2026-07-28T05:10:00.000Z' },
  { id: '2', sessionId: 'ses-1ac9', activeProblemId: 'IAM-1', status: 'SYNTHESIZING', targetArn: 'arn:aws:iam::123456789012:role/DeploymentRole', zelkovaStatus: 'UNVERIFIED', blastRadiusScore: null, createdAt: '2026-07-28T04:42:00.000Z' },
  { id: '3', sessionId: 'ses-8d22', activeProblemId: 'SCP-5', status: 'COMMITTED', targetArn: 'arn:aws:organizations::123456789012:ou/o-example/ou-prod', zelkovaStatus: 'PASS', blastRadiusScore: 0.04, createdAt: '2026-07-27T23:18:00.000Z' }
];

async function getSessions(): Promise<SessionSummary[]> { return mockSessions; }

const statusConfig: Record<SessionSummary['status'], { label: string; bg: string; icon: typeof Shield }> = {
  ROUTING: { label: 'Routing', bg: 'bg-sky-500/15 text-sky-300 border-sky-500/20', icon: Activity },
  SYNTHESIZING: { label: 'Synthesizing', bg: 'bg-violet-500/15 text-violet-300 border-violet-500/20', icon: Clock },
  AWAITING_HITL: { label: 'Awaiting HITL', bg: 'bg-amber-500/15 text-amber-300 border-amber-500/20', icon: AlertTriangle },
  COMMITTED: { label: 'Committed', bg: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/20', icon: CheckCircle },
  FAILED: { label: 'Failed', bg: 'bg-rose-500/15 text-rose-300 border-rose-500/20', icon: Shield }
};

const zelkovaConfig: Record<string, { label: string; bg: string }> = {
  PASS: { label: 'Pass', bg: 'bg-emerald-500/10 text-emerald-300' },
  FAIL_PRIVILEGE_ESCALATION: { label: 'Violation', bg: 'bg-rose-500/10 text-rose-300' },
  UNVERIFIED: { label: 'Unverified', bg: 'bg-zinc-700/50 text-zinc-400' }
};

export function SessionDashboard(): JSX.Element {
  const { data, isLoading, isError } = useQuery({ queryKey: ['sessions'], queryFn: getSessions });

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-8">
        <div className="flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-cyan-500/10">
            <Shield size={20} className="text-cyan-400" />
          </span>
          <div>
            <h1 className="text-2xl font-semibold text-zinc-100">Governance sessions</h1>
            <p className="mt-1 text-sm text-zinc-500">Monitor policy drift analysis and human approval queues.</p>
          </div>
        </div>
      </div>

      {data && data.length > 0 && (
        <div className="mb-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {[
            { label: 'Total sessions', value: data.length, color: 'text-zinc-100' },
            { label: 'Awaiting review', value: data.filter((s) => s.status === 'AWAITING_HITL').length, color: 'text-amber-300' },
            { label: 'Committed', value: data.filter((s) => s.status === 'COMMITTED').length, color: 'text-emerald-300' },
            { label: 'Avg blast radius', value: data.filter((s) => s.blastRadiusScore !== null).length > 0 ? `${Math.round(data.filter((s) => s.blastRadiusScore !== null).reduce((a, s) => a + (s.blastRadiusScore ?? 0), 0) / data.filter((s) => s.blastRadiusScore !== null).length * 100)}%` : '—', color: 'text-zinc-100' },
          ].map((stat) => (
            <div key={stat.label} className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-4 transition hover:border-zinc-700/80 hover:bg-zinc-900/80">
              <p className="text-xs font-medium uppercase tracking-wider text-zinc-500">{stat.label}</p>
              <p className={`mt-2 text-2xl font-semibold ${stat.color}`}>{stat.value}</p>
            </div>
          ))}
        </div>
      )}

      {isLoading && (
        <div className="flex items-center justify-center rounded-xl border border-zinc-800 bg-zinc-900/60 p-12">
          <div className="flex items-center gap-3">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-zinc-600 border-t-cyan-400" />
            <span className="text-sm text-zinc-400">Loading sessions…</span>
          </div>
        </div>
      )}

      {isError && (
        <div role="alert" className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-6">
          <div className="flex items-center gap-3">
            <AlertTriangle size={20} className="text-rose-400" />
            <p className="text-sm font-medium text-rose-200">Unable to load sessions. Try again shortly.</p>
          </div>
        </div>
      )}

      {data?.length === 0 && (
        <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-12 text-center">
          <Shield size={40} className="mx-auto text-zinc-600" />
          <h2 className="mt-4 text-lg font-semibold text-zinc-300">No governance sessions found</h2>
          <p className="mt-2 text-sm text-zinc-500">New sessions will appear here when policy drift is detected.</p>
        </div>
      )}

      {data && data.length > 0 && (
        <div className="overflow-hidden rounded-xl border border-zinc-800 bg-zinc-900/40">
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b border-zinc-800 bg-zinc-900/80">
                  <th className="px-5 py-3.5 text-xs font-semibold uppercase tracking-wider text-zinc-400">Session</th>
                  <th className="px-5 py-3.5 text-xs font-semibold uppercase tracking-wider text-zinc-400">Problem</th>
                  <th className="px-5 py-3.5 text-xs font-semibold uppercase tracking-wider text-zinc-400">Status</th>
                  <th className="px-5 py-3.5 text-xs font-semibold uppercase tracking-wider text-zinc-400">Proof</th>
                  <th className="px-5 py-3.5 text-xs font-semibold uppercase tracking-wider text-zinc-400">Blast radius</th>
                  <th className="px-5 py-3.5 text-xs font-semibold uppercase tracking-wider text-zinc-400">Created</th>
                  <th className="px-5 py-3.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-800/60">
                {data.map((session) => {
                  const status = statusConfig[session.status];
                  const StatusIcon = status.icon;
                  const zelkova = session.zelkovaStatus ? zelkovaConfig[session.zelkovaStatus] ?? zelkovaConfig.UNVERIFIED : zelkovaConfig.UNVERIFIED;
                  return (
                    <tr key={session.id} className="group bg-zinc-950/30 transition-all duration-200 hover:bg-zinc-900/60">
                      <td className="px-5 py-4">
                        <Link href={`/sessions/${session.id}`} className="font-medium text-cyan-300 transition hover:text-cyan-200">
                          {session.sessionId}
                        </Link>
                      </td>
                      <td className="px-5 py-4 font-mono text-xs text-zinc-300">{session.activeProblemId}</td>
                      <td className="px-5 py-4">
                        <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${status.bg}`}>
                          <StatusIcon size={12} />
                          {status.label}
                        </span>
                      </td>
                      <td className="px-5 py-4">
                        <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ${zelkova.bg}`}>
                          {zelkova.label}
                        </span>
                      </td>
                      <td className="px-5 py-4">
                        <div className="flex items-center gap-2">
                          <div className="h-1.5 w-20 overflow-hidden rounded-full bg-zinc-800">
                            <div
                              className={`h-full rounded-full transition-all ${
                                session.blastRadiusScore === null ? 'bg-zinc-700' :
                                session.blastRadiusScore > 0.5 ? 'bg-rose-500' :
                                session.blastRadiusScore > 0.1 ? 'bg-amber-400' : 'bg-emerald-400'
                              }`}
                              style={{ width: `${session.blastRadiusScore === null ? 0 : Math.min(100, session.blastRadiusScore * 100)}%` }}
                            />
                          </div>
                          <span className="text-xs text-zinc-400">
                            {session.blastRadiusScore === null ? '—' : `${Math.round(session.blastRadiusScore * 100)}%`}
                          </span>
                        </div>
                      </td>
                      <td className="px-5 py-4 text-xs text-zinc-500">{new Date(session.createdAt).toLocaleString()}</td>
                      <td className="px-5 py-4">
                        <Link
                          href={`/sessions/${session.id}`}
                          className="flex h-8 w-8 items-center justify-center rounded-lg text-zinc-600 opacity-0 transition-all hover:bg-zinc-800 hover:text-zinc-300 group-hover:opacity-100"
                        >
                          <ArrowRight size={16} />
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
