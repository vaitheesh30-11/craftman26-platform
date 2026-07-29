'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import axios from 'axios';
import apiClient from '@/lib/api-client';
import { useToast } from '@/components/providers/ToastProvider';
import type { ApprovalPayload, RejectionPayload, SessionDetail, SessionStatus, ZelkovaStatus } from '@/types/dto';

interface ApiSessionDetail {
  id: string;
  session_id: string;
  account_id: string;
  active_problem_id: string;
  status: SessionStatus;
  target_arn: string;
  baseline_policy_json: string | null;
  working_policy_json: string | null;
  zelkova_status: ZelkovaStatus | null;
  blast_radius_score: number | null;
  problem_telemetry: Record<string, unknown>;
  state_tensor_snapshot: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

const baselinePolicy = JSON.stringify({ Version: '2012-10-17', Statement: [{ Sid: 'DenyUnencryptedS3', Effect: 'Deny', Action: 's3:PutObject', Resource: '*', Condition: { Null: { 's3:x-amz-server-side-encryption': 'true' } } }] }, null, 2);
const workingPolicy = JSON.stringify({ Version: '2012-10-17', Statement: [{ Sid: 'DenyUnencryptedS3', Effect: 'Deny', Action: 's3:PutObject', Resource: '*', Condition: { Null: { 's3:x-amz-server-side-encryption': 'true' } } }, { Sid: 'AllowSecurityReadOnly', Effect: 'Allow', Action: ['iam:GetRole', 'iam:ListRoles'], Resource: '*' }] }, null, 2);

function toSessionDetail(data: ApiSessionDetail): SessionDetail {
  return { id: data.id, sessionId: data.session_id, accountId: data.account_id, activeProblemId: data.active_problem_id, status: data.status, targetArn: data.target_arn, baselinePolicyJson: data.baseline_policy_json, workingPolicyJson: data.working_policy_json, zelkovaStatus: data.zelkova_status, blastRadiusScore: data.blast_radius_score, problemTelemetry: data.problem_telemetry, stateTensorSnapshot: data.state_tensor_snapshot, createdAt: data.created_at, updatedAt: data.updated_at };
}

function mockSessionDetail(sessionId: string): SessionDetail {
  const now = new Date().toISOString();
  return { id: sessionId, sessionId, accountId: '123456789012', activeProblemId: 'SCP-2', status: 'AWAITING_HITL', targetArn: 'arn:aws:organizations::123456789012:policy/o-root/scp-guardrails', baselinePolicyJson: baselinePolicy, workingPolicyJson: workingPolicy, zelkovaStatus: 'PASS', blastRadiusScore: 0.18, problemTelemetry: { inherited_scp_ids: ['p-baseline'], effective_deny_actions: ['s3:PutObject'] }, stateTensorSnapshot: {}, createdAt: now, updatedAt: now };
}

export const shouldUseMocks = (): boolean => process.env.NEXT_PUBLIC_USE_MOCK_DATA !== 'false';

export function useGetSessionDetail(sessionId: string) {
  return useQuery({ queryKey: ['session-detail', sessionId], enabled: Boolean(sessionId), queryFn: async (): Promise<SessionDetail> => {
    if (shouldUseMocks()) return mockSessionDetail(sessionId);
    const response = await apiClient.get<ApiSessionDetail>(`/api/v1/sessions/${encodeURIComponent(sessionId)}`);
    return toSessionDetail(response.data);
  } });
}

export interface ApproveSessionInput extends ApprovalPayload { sessionId: string; }
export function useApproveSessionMutation() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  return useMutation({
    mutationFn: async ({ sessionId, ...payload }: ApproveSessionInput): Promise<void> => {
      if (shouldUseMocks()) { await new Promise<void>((resolve) => window.setTimeout(resolve, 650)); return; }
      await apiClient.post(`/api/v1/sessions/${encodeURIComponent(sessionId)}/approve`, { approver_arn: payload.approverArn, approval_notes: payload.approvalNotes, override_policy_json: payload.overridePolicyJson });
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: ['session-detail', input.sessionId] });
      const previous = queryClient.getQueryData<SessionDetail>(['session-detail', input.sessionId]);
      if (previous) queryClient.setQueryData<SessionDetail>(['session-detail', input.sessionId], { ...previous, status: 'COMMITTED' });
      return { previous };
    },
    onError: (error, input, context) => {
      if (context?.previous) queryClient.setQueryData(['session-detail', input.sessionId], context.previous);
      const detail = axios.isAxiosError(error) ? (typeof error.response?.data?.detail === 'string' ? error.response.data.detail : error.message) : 'The approval could not be committed. Please retry.';
      showToast({ tone: 'error', title: 'Deployment was not committed', detail });
    },
    onSuccess: (_, input) => { queryClient.invalidateQueries({ queryKey: ['sessions'] }); queryClient.invalidateQueries({ queryKey: ['session-detail', input.sessionId] }); showToast({ tone: 'success', title: 'Mutation committed to AWS', detail: 'The approval record was created successfully.' }); }
  });
}

export interface RejectSessionInput extends RejectionPayload { sessionId: string; }
export function useRejectSessionMutation() {
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  return useMutation({
    mutationFn: async ({ sessionId, ...payload }: RejectSessionInput): Promise<void> => {
      if (shouldUseMocks()) { await new Promise<void>((resolve) => window.setTimeout(resolve, 450)); return; }
      await apiClient.post(`/api/v1/sessions/${encodeURIComponent(sessionId)}/reject`, { approver_arn: payload.approverArn, rejection_reason: payload.rejectionReason });
    },
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: ['session-detail', input.sessionId] });
      const previous = queryClient.getQueryData<SessionDetail>(['session-detail', input.sessionId]);
      if (previous) queryClient.setQueryData<SessionDetail>(['session-detail', input.sessionId], { ...previous, status: 'FAILED' });
      return { previous };
    },
    onError: (error, input, context) => {
      if (context?.previous) queryClient.setQueryData(['session-detail', input.sessionId], context.previous);
      const detail = axios.isAxiosError(error) && typeof error.response?.data?.detail === 'string' ? error.response.data.detail : 'The session could not be rejected. Please retry.';
      showToast({ tone: 'error', title: 'Rejection was not recorded', detail });
    },
    onSuccess: (_, input) => { queryClient.invalidateQueries({ queryKey: ['sessions'] }); queryClient.invalidateQueries({ queryKey: ['session-detail', input.sessionId] }); showToast({ tone: 'success', title: 'Session rejected', detail: 'The governed deployment has been stopped.' }); }
  });
}
