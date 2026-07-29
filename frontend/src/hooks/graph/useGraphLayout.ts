'use client';

import dagre from 'dagre';
import { useMemo } from 'react';
import type { TrustFlowEdge, TrustFlowNode } from '@/types/graph';

const NODE_WIDTH = 224;
const NODE_HEIGHT = 96;

export function layoutGraph(nodes: TrustFlowNode[], edges: TrustFlowEdge[], direction: 'LR' | 'TB' = 'LR'): TrustFlowNode[] {
  const graph = new dagre.graphlib.Graph();
  graph.setDefaultEdgeLabel(() => ({}));
  graph.setGraph({ rankdir: direction, ranksep: 150, nodesep: 46, marginx: 32, marginy: 32 });
  nodes.forEach((node) => graph.setNode(node.id, { width: NODE_WIDTH, height: NODE_HEIGHT }));
  edges.forEach((edge) => graph.setEdge(edge.source, edge.target));
  dagre.layout(graph);
  return nodes.map((node) => {
    const position = graph.node(node.id) as { x: number; y: number };
    return { ...node, position: { x: position.x - NODE_WIDTH / 2, y: position.y - NODE_HEIGHT / 2 } };
  });
}

export function useGraphLayout(nodes: TrustFlowNode[], edges: TrustFlowEdge[], direction: 'LR' | 'TB' = 'LR'): TrustFlowNode[] {
  return useMemo(() => layoutGraph(nodes, edges, direction), [direction, edges, nodes]);
}
