export type SessionStatus =
  | 'ROUTING'
  | 'SYNTHESIZING'
  | 'AWAITING_HITL'
  | 'COMMITTED'
  | 'FAILED';

export type ZelkovaStatus = 'PASS' | 'FAIL_PRIVILEGE_ESCALATION' | 'UNVERIFIED';

export interface SessionSummary {
  id: string;
  sessionId: string;
  activeProblemId: string;
  status: SessionStatus;
  targetArn: string;
  zelkovaStatus: ZelkovaStatus | null;
  blastRadiusScore: number | null;
  createdAt: string;
}

export interface ApprovalPayload {
  approverArn: string;
  overridePolicyJson: string | null;
  approvalNotes: string;
}

export interface RejectionPayload {
  approverArn: string;
  rejectionReason: string;
}

export interface SessionDetail extends SessionSummary {
  accountId: string;
  baselinePolicyJson: string | null;
  workingPolicyJson: string | null;
  problemTelemetry: Record<string, unknown>;
  stateTensorSnapshot: Record<string, unknown>;
  updatedAt: string;
}
