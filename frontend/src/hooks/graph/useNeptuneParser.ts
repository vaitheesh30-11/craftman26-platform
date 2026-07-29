'use client';

import { useMemo } from 'react';
import type { NeptunePath, GraphEndpoint, TrustFlowEdge, TrustFlowNode, TrustNodeKind } from '@/types/graph';

const defaultPolicies = ['{\n  "Version": "2012-10-17",\n  "Statement": []\n}'];
const slug = (value: string): string => value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');

function toEndpoint(value: string | GraphEndpoint): Required<GraphEndpoint> {
  if (typeof value === 'string') {
    const nodeKind: TrustNodeKind = value.includes('Account') || /^\d{12}$/.test(value) ? 'ACCOUNT' : value.includes('vendor') ? 'EXTERNAL_VENDOR' : 'ROLE';
    return { id: slug(value), label: value, type: nodeKind, isCompromised: false, policies: defaultPolicies };
  }
  return { id: value.id ?? slug(value.label), label: value.label, type: value.type ?? 'ROLE', isCompromised: value.isCompromised ?? false, policies: value.policies ?? defaultPolicies };
}

function retainDepth(paths: NeptunePath[], maxDepth: number): NeptunePath[] {
  if (paths.length === 0) return [];
  const endpoints = paths.map((path) => ({ source: toEndpoint(path.source), target: toEndpoint(path.target), path }));
  const root = endpoints[0].source.id;
  const adjacency = new Map<string, string[]>();
  endpoints.forEach(({ source, target }) => adjacency.set(source.id, [...(adjacency.get(source.id) ?? []), target.id]));
  const depths = new Map<string, number>([[root, 0]]);
  const queue = [root];
  while (queue.length > 0) {
    const current = queue.shift() as string;
    const depth = depths.get(current) ?? 0;
    if (depth >= maxDepth) continue;
    for (const next of adjacency.get(current) ?? []) if (!depths.has(next)) { depths.set(next, depth + 1); queue.push(next); }
  }
  return endpoints.filter(({ source, target }) => depths.has(source.id) && depths.has(target.id)).map(({ path }) => path);
}

export function parseNeptunePaths(paths: NeptunePath[], maxDepth = 2): { nodes: TrustFlowNode[]; edges: TrustFlowEdge[] } {
  const nodeMap = new Map<string, TrustFlowNode>();
  const edges: TrustFlowEdge[] = [];
  retainDepth(paths, maxDepth).forEach((path, index) => {
    const source = toEndpoint(path.source);
    const target = toEndpoint(path.target);
    [source, target].forEach((endpoint) => {
      const existing = nodeMap.get(endpoint.id);
      nodeMap.set(endpoint.id, { id: endpoint.id, type: endpoint.type === 'ACCOUNT' || endpoint.type === 'OU' ? 'accountNode' : 'iamRoleNode', position: { x: 0, y: 0 }, data: { label: endpoint.label, nodeKind: endpoint.type, isCompromised: endpoint.isCompromised || existing?.data.isCompromised === true, policies: endpoint.policies } });
    });
    edges.push({ id: `trust-${source.id}-${target.id}-${index}`, type: 'trustEdge', source: source.id, target: target.id, animated: path.isVulnerable ?? false, data: { relation: path.relation, isVulnerable: path.isVulnerable ?? false, missingCondition: path.missingCondition } });
  });
  return { nodes: Array.from(nodeMap.values()), edges };
}

export function useNeptuneParser(paths: NeptunePath[], maxDepth = 2): { nodes: TrustFlowNode[]; edges: TrustFlowEdge[] } {
  return useMemo(() => parseNeptunePaths(paths, maxDepth), [maxDepth, paths]);
}

export const mockTrustPaths: NeptunePath[] = [
  { source: { label: 'Vendor-Analytics', type: 'EXTERNAL_VENDOR', policies: ['{ "Principal": "vendor.example.com", "Action": "sts:AssumeRole" }'] }, target: { label: 'analytics-ingest-role', type: 'ROLE', policies: ['{ "Condition": { "StringEquals": { "aws:SourceAccount": "123456789012" } } }'] }, relation: 'ASSUMES_ROLE' },
  { source: { label: 'analytics-ingest-role', type: 'ROLE', policies: ['{ "Action": "sts:AssumeRole", "Resource": "arn:aws:iam::123456789012:role/prod-db-role" }'] }, target: { label: 'prod-db-role', type: 'ROLE', isCompromised: true, policies: ['{ "Principal": "arn:aws:iam::444455556666:role/analytics-ingest-role", "Condition": {} }'] }, relation: 'ASSUMES_ROLE', isVulnerable: true, missingCondition: 'aws:SourceArn is missing from this trust relationship' },
  { source: { label: 'prod-db-role', type: 'ROLE', isCompromised: true }, target: { label: '123456789012', type: 'ACCOUNT', policies: ['{ "Account": "123456789012", "OU": "prod-workloads" }'] }, relation: 'ASSUMES_ROLE', isVulnerable: true, missingCondition: 'Privilege path reaches the production account' }
];
