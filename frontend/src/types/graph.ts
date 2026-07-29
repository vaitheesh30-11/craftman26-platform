import type { Edge, Node } from '@xyflow/react';

export type TrustNodeKind = 'ACCOUNT' | 'OU' | 'ROLE' | 'EXTERNAL_VENDOR';

export interface GraphEndpoint {
  id?: string;
  label: string;
  type?: TrustNodeKind;
  isCompromised?: boolean;
  policies?: string[];
}

export interface NeptunePath {
  source: string | GraphEndpoint;
  target: string | GraphEndpoint;
  relation: 'ASSUMES_ROLE' | string;
  isVulnerable?: boolean;
  missingCondition?: string;
}

export interface TrustNodeData extends Record<string, unknown> {
  label: string;
  nodeKind: TrustNodeKind;
  isCompromised: boolean;
  policies: string[];
}

export interface TrustEdgeData extends Record<string, unknown> {
  relation: string;
  isVulnerable: boolean;
  missingCondition?: string;
}

export type TrustFlowNode = Node<TrustNodeData, 'accountNode' | 'iamRoleNode'>;
export type TrustFlowEdge = Edge<TrustEdgeData, 'trustEdge'>;
