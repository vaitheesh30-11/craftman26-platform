'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useSessionStore } from '@/store/useSessionStore';
import type { ConnectionState, StreamEvent } from '@/types/stream';

const MAX_EVENTS = 50;
const HEARTBEAT_MS = 10_000;
const PONG_TIMEOUT_MS = 5_000;
const MAX_RETRY_MS = 16_000;

interface WebSocketStreamState {
  connectionState: ConnectionState;
  pingLatencyMs: number | null;
  latestEvents: StreamEvent[];
}

function isStreamEvent(value: unknown): value is StreamEvent {
  if (typeof value !== 'object' || value === null) return false;
  const event = value as Partial<StreamEvent>;
  return typeof event.event_id === 'string' && typeof event.session_id === 'string' && typeof event.timestamp === 'string' && typeof event.event_type === 'string';
}

function appendEvent(current: StreamEvent[], event: StreamEvent): StreamEvent[] {
  if (event.event_type === 'STATE_SYNC' && 'debate_log' in event && event.debate_log) return event.debate_log.slice(-MAX_EVENTS);
  if (current.some((item) => item.event_id === event.event_id)) return current;
  return [...current, event].slice(-MAX_EVENTS);
}

function createMockEvent(sessionId: string, sequence: number): StreamEvent {
  const events: StreamEvent[] = [
    { event_id: `mock-${sequence}`, session_id: sessionId, timestamp: new Date().toISOString(), event_type: 'AGENT_TURN_EMITTED', coalition: 'SUPERVISOR', agent_id: 'Supervisor_Node', action_taken: 'Routing the policy drift signal to the synthesis coalition.', execution_duration_ms: 84 },
    { event_id: `mock-${sequence}`, session_id: sessionId, timestamp: new Date().toISOString(), event_type: 'AGENT_TURN_EMITTED', coalition: 'ALPHA_SYNTHESIS', agent_id: 'AST_Compiler_Agent', action_taken: 'Normalized the policy AST and removed redundant deny branches.', formal_feedback: 'Candidate remains within the configured quota.', execution_duration_ms: 340, tool_parameters: { normalized_statements: 7, removed_nodes: 2 } },
    { event_id: `mock-${sequence}`, session_id: sessionId, timestamp: new Date().toISOString(), event_type: 'PROOF_STATUS_UPDATED', zelkova_status: 'PASS', counter_examples: [], blast_radius_score: 0.18 }
  ];
  return events[sequence % events.length];
}

/** Owns browser socket lifecycle; missing WS configuration deliberately uses a local preview stream. */
export function useWebSocketStream(sessionId: string, enabled: boolean): WebSocketStreamState {
  const [state, setState] = useState<WebSocketStreamState>({ connectionState: 'DISCONNECTED', pingLatencyMs: null, latestEvents: [] });
  const setStreamSession = useSessionStore((store) => store.setStreamSession);
  const setConnectionState = useSessionStore((store) => store.setConnectionState);
  const setPingLatency = useSessionStore((store) => store.setPingLatency);
  const appendStreamEvent = useSessionStore((store) => store.appendStreamEvent);
  const retryAttempt = useRef(0);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const heartbeatTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const pongTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const wsUrl = useMemo(() => process.env.NEXT_PUBLIC_WS_URL, []);

  useEffect(() => {
    if (!enabled || !sessionId) return;
    setStreamSession(sessionId);
    let socket: WebSocket | null = null;
    let disposed = false;
    let mockTimer: ReturnType<typeof setInterval> | null = null;

    const clearTimers = (): void => {
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      if (heartbeatTimer.current) clearInterval(heartbeatTimer.current);
      if (pongTimer.current) clearTimeout(pongTimer.current);
      reconnectTimer.current = heartbeatTimer.current = pongTimer.current = null;
    };
    const push = (event: StreamEvent): void => {
      appendStreamEvent(event);
      setState((current) => ({ ...current, latestEvents: appendEvent(current.latestEvents, event) }));
    };

    if (!wsUrl) {
      setState((current) => ({ ...current, connectionState: 'LIVE', pingLatencyMs: 0 }));
      setConnectionState('LIVE');
      setPingLatency(0);
      let sequence = 0;
      push(createMockEvent(sessionId, sequence++));
      mockTimer = setInterval(() => push(createMockEvent(sessionId, sequence++)), 2_500);
      return () => { if (mockTimer) clearInterval(mockTimer); };
    }

    const connect = (): void => {
      if (disposed) return;
      setState((current) => ({ ...current, connectionState: retryAttempt.current ? 'RECONNECTING' : 'CONNECTING' }));
      setConnectionState(retryAttempt.current ? 'RECONNECTING' : 'CONNECTING');
      const token = process.env.NEXT_PUBLIC_WS_TOKEN;
      const url = new URL(`${wsUrl.replace(/\/$/, '')}/ws/drift/${encodeURIComponent(sessionId)}`);
      if (token) url.searchParams.set('token', token);
      socket = new WebSocket(url.toString());
      socket.onopen = () => {
        retryAttempt.current = 0;
        setState((current) => ({ ...current, connectionState: 'LIVE' }));
        setConnectionState('LIVE');
        socket?.send(JSON.stringify({ event_type: 'STATE_SYNC_REQUEST', session_id: sessionId }));
        heartbeatTimer.current = setInterval(() => {
          const sentAt = Date.now();
          socket?.send(JSON.stringify({ event_type: 'PING', sent_at: sentAt }));
          pongTimer.current = setTimeout(() => socket?.close(), PONG_TIMEOUT_MS);
        }, HEARTBEAT_MS);
      };
      socket.onmessage = (message) => {
        try {
          const payload: unknown = JSON.parse(String(message.data));
          if (typeof payload === 'object' && payload !== null && (payload as { event_type?: string }).event_type === 'PONG') {
            if (pongTimer.current) clearTimeout(pongTimer.current);
            const sentAt = (payload as { sent_at?: number }).sent_at;
            if (typeof sentAt === 'number') {
              const latency = Date.now() - sentAt;
              setState((current) => ({ ...current, pingLatencyMs: latency }));
              setPingLatency(latency);
            }
          } else if (isStreamEvent(payload)) push(payload);
        } catch { /* Ignore malformed stream frames without disrupting the active session. */ }
      };
      socket.onclose = () => {
        if (disposed) return;
        clearTimers();
        const delay = Math.min(1_000 * 2 ** retryAttempt.current++, MAX_RETRY_MS);
        setState((current) => ({ ...current, connectionState: 'RECONNECTING' }));
        setConnectionState('RECONNECTING');
        reconnectTimer.current = setTimeout(connect, delay);
      };
      socket.onerror = () => socket?.close();
    };
    connect();
    return () => { disposed = true; clearTimers(); socket?.close(); };
  }, [appendStreamEvent, enabled, sessionId, setConnectionState, setPingLatency, setStreamSession, wsUrl]);

  return state;
}
