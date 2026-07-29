export type ConnectionState = 'CONNECTING' | 'LIVE' | 'RECONNECTING' | 'DISCONNECTED';
export type Coalition = 'SUPERVISOR' | 'ALPHA_SYNTHESIS' | 'BETA_SIMULATION' | 'GAMMA_CONTEXT';
export type StreamEventType = 'STATE_SYNC' | 'AGENT_TURN_EMITTED' | 'POLICY_AST_UPDATED' | 'PROOF_STATUS_UPDATED' | 'INTERRUPT_REACHED' | 'MUTATION_COMMITTED';

export interface StreamEventBase {
  event_id: string;
  session_id: string;
  timestamp: string;
  event_type: StreamEventType;
}

export interface AgentTurnEvent extends StreamEventBase {
  event_type: 'AGENT_TURN_EMITTED';
  coalition: Coalition;
  agent_id: string;
  action_taken: string;
  formal_feedback?: string | null;
  execution_duration_ms?: number;
  tool_parameters?: Record<string, unknown>;
}

export interface PolicyAstUpdatedEvent extends StreamEventBase {
  event_type: 'POLICY_AST_UPDATED';
  working_policy_json: string;
  byte_size: number;
}

export interface ProofStatusUpdatedEvent extends StreamEventBase {
  event_type: 'PROOF_STATUS_UPDATED';
  zelkova_status: 'PASS' | 'FAIL_PRIVILEGE_ESCALATION';
  counter_examples: string[];
  blast_radius_score: number;
}

export interface StateSyncEvent extends StreamEventBase {
  event_type: 'STATE_SYNC';
  debate_log?: AgentTurnEvent[];
}

export type StreamEvent = AgentTurnEvent | PolicyAstUpdatedEvent | ProofStatusUpdatedEvent | StateSyncEvent | StreamEventBase;

export interface ExecutionMetrics {
  iteration: number;
  maxIterations: number;
  tokenBurnRate: number;
  policyBytes: number;
  zelkovaStatus: 'PASS' | 'FAIL_PRIVILEGE_ESCALATION' | 'UNVERIFIED';
  alertCount: number;
  blastRadiusScore: number;
}
