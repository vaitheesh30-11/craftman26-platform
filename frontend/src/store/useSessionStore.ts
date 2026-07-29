'use client';

import { create } from 'zustand';
import type { ConnectionState, StreamEvent } from '@/types/stream';

export type WorkspaceTab = 'DIFF_VIEWER' | 'TOPOLOGY_MAP' | 'DEBATE_LOG';

interface SessionStore {
  isSidebarOpen: boolean;
  activeWorkspaceTab: WorkspaceTab;
  setSidebarOpen: (isOpen: boolean) => void;
  setWorkspaceTab: (tab: WorkspaceTab) => void;
  streamSessionId: string | null;
  streamState: ConnectionState;
  pingLatencyMs: number | null;
  latestEvents: StreamEvent[];
  setStreamSession: (sessionId: string) => void;
  setConnectionState: (state: ConnectionState) => void;
  setPingLatency: (latency: number | null) => void;
  appendStreamEvent: (event: StreamEvent) => void;
}

export const useSessionStore = create<SessionStore>((set) => ({
  isSidebarOpen: true,
  activeWorkspaceTab: 'DIFF_VIEWER',
  setSidebarOpen: (isSidebarOpen) => set({ isSidebarOpen }),
  setWorkspaceTab: (activeWorkspaceTab) => set({ activeWorkspaceTab }),
  streamSessionId: null,
  streamState: 'DISCONNECTED',
  pingLatencyMs: null,
  latestEvents: [],
  setStreamSession: (sessionId) => set((current) => current.streamSessionId === sessionId ? current : { streamSessionId: sessionId, streamState: 'DISCONNECTED', pingLatencyMs: null, latestEvents: [] }),
  setConnectionState: (streamState) => set({ streamState }),
  setPingLatency: (pingLatencyMs) => set({ pingLatencyMs }),
  appendStreamEvent: (event) => set((current) => {
    const syncedEvents = event.event_type === 'STATE_SYNC' && 'debate_log' in event && event.debate_log ? event.debate_log : [...current.latestEvents, event];
    const deduplicated = syncedEvents.filter((item, index, all) => all.findIndex((candidate) => candidate.event_id === item.event_id) === index).slice(-50);
    return { latestEvents: deduplicated };
  })
}));
