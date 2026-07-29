'use client';

import { useEffect, useState } from 'react';
import { shouldUseMocks, useApproveSessionMutation, useRejectSessionMutation } from '@/hooks/api/useSessionApi';
import { useToast } from '@/components/providers/ToastProvider';
import type { ZelkovaStatus } from '@/types/dto';
import { getPolicyByteLength } from '@/components/editor/ByteQuotaGauge';
import { ManualOverrideModal } from './ManualOverrideModal';
import { RejectSessionModal } from './RejectSessionModal';

interface HITLControlPanelProps { sessionId: string; targetPolicyJson: string; isJsonValid: boolean; isDirty: boolean; zelkovaStatus: ZelkovaStatus | null; onProofComplete: () => void; }

export function HITLControlPanel({ sessionId, targetPolicyJson, isJsonValid, isDirty, zelkovaStatus, onProofComplete }: HITLControlPanelProps): JSX.Element {
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [isRejectModalOpen, setIsRejectModalOpen] = useState(false);
  const [isProofing, setIsProofing] = useState(false);
  const [freshProofForOverride, setFreshProofForOverride] = useState(false);
  const { showToast } = useToast();
  const approve = useApproveSessionMutation();
  const reject = useRejectSessionMutation();
  const quotaExceeded = getPolicyByteLength(targetPolicyJson) >= 10_240;
  useEffect(() => { setFreshProofForOverride(false); }, [targetPolicyJson]);
  const unsafe = !isJsonValid || quotaExceeded || zelkovaStatus === 'FAIL_PRIVILEGE_ESCALATION';
  const proofRequired = isDirty && !freshProofForOverride;
  const blocked = unsafe || (!isDirty && zelkovaStatus !== 'PASS');
  const beginProof = (): void => {
    if (!shouldUseMocks()) {
      showToast({ tone: 'info', title: 'Proof will run before deployment', detail: 'The governed approval submits your override for a fresh proof before any deployment can proceed.' });
      setIsModalOpen(true);
      return;
    }
    setIsProofing(true);
    window.setTimeout(() => { setIsProofing(false); setFreshProofForOverride(true); onProofComplete(); showToast({ tone: 'success', title: 'Zelkova proof passed', detail: 'The edited policy is cleared for deployment.' }); }, 950);
  };
  const confirmApproval = (approverArn: string, approvalNotes: string): void => approve.mutate({ sessionId, approverArn, approvalNotes, overridePolicyJson: isDirty ? targetPolicyJson : null }, { onSuccess: () => setIsModalOpen(false) });
  const action = unsafe ? { label: 'Deployment blocked', className: 'border-rose-500/60 bg-rose-500/10 text-rose-200', disabled: true, handler: () => undefined } : proofRequired ? { label: isProofing ? 'Running Zelkova proof…' : 'Re-run Zelkova SMT proof', className: 'border-violet-400/60 bg-violet-500/15 text-violet-100 hover:bg-violet-500/25', disabled: isProofing, handler: beginProof } : blocked ? { label: 'Awaiting verified proof', className: 'border-amber-500/60 bg-amber-500/10 text-amber-200', disabled: true, handler: () => undefined } : { label: 'Approve & deploy to AWS', className: 'border-emerald-400/60 bg-emerald-500 text-zinc-950 hover:bg-emerald-400', disabled: approve.isPending, handler: () => setIsModalOpen(true) };
  const proofTone = zelkovaStatus === 'PASS' ? 'border-emerald-500/50 bg-emerald-500/10 text-emerald-300' : zelkovaStatus === 'FAIL_PRIVILEGE_ESCALATION' ? 'border-rose-500/50 bg-rose-500/10 text-rose-300' : 'border-amber-500/50 bg-amber-500/10 text-amber-300';
  const confirmRejection = (approverArn: string, rejectionReason: string): void => reject.mutate({ sessionId, approverArn, rejectionReason }, { onSuccess: () => setIsRejectModalOpen(false) });
  return <aside className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-5 shadow-xl shadow-black/10"><div className="flex items-start justify-between gap-3"><div><p className="text-xs font-semibold uppercase tracking-[0.18em] text-cyan-400">Approval gate</p><h2 className="mt-2 text-lg font-semibold text-zinc-100">Human-in-the-loop control</h2></div><span className={`rounded-full border px-2.5 py-1 text-xs font-semibold ${proofTone}`}>{zelkovaStatus ?? 'UNVERIFIED'}</span></div><ul className="mt-5 space-y-3 text-sm text-zinc-400"><li className="flex gap-3"><span className="text-emerald-400">✓</span>Policy diff recorded for audit review</li><li className="flex gap-3"><span className={isDirty ? 'text-violet-300' : 'text-emerald-400'}>{isDirty ? '•' : '✓'}</span>{isDirty ? 'Manual changes require fresh mathematical proof' : 'No unverified manual policy changes'}</li><li className="flex gap-3"><span className={blocked ? 'text-rose-400' : 'text-emerald-400'}>{blocked ? '!' : '✓'}</span>{blocked ? 'A verified PASS proof, valid JSON, and quota compliance are required' : 'Quota and JSON validation checks passed'}</li></ul><button type="button" disabled={action.disabled} onClick={action.handler} className={`mt-6 w-full rounded-xl border px-4 py-3 text-sm font-semibold shadow-lg transition focus:outline-none focus:ring-2 focus:ring-cyan-400 focus:ring-offset-2 focus:ring-offset-zinc-950 disabled:cursor-not-allowed disabled:opacity-60 ${action.className}`}>{action.label}</button><button type="button" disabled={reject.isPending} onClick={() => setIsRejectModalOpen(true)} className="mt-3 w-full rounded-xl border border-rose-500/40 px-4 py-3 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/10 disabled:cursor-not-allowed disabled:opacity-60">Reject session</button><p className="mt-3 text-center text-xs text-zinc-500">Every approval or rejection requires an auditable identity and justification.</p><ManualOverrideModal open={isModalOpen} onOpenChange={setIsModalOpen} isPending={approve.isPending} hasOverride={isDirty} onConfirm={confirmApproval} /><RejectSessionModal open={isRejectModalOpen} onOpenChange={setIsRejectModalOpen} isPending={reject.isPending} onConfirm={confirmRejection} /></aside>;
}
