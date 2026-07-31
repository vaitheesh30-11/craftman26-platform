import { getPublicEnv } from "@/lib/env";

export interface ChatQuery {
  query_text: string;
  hints?: Record<string, string>;
  include_arns_in_output?: boolean;
}

export interface ErrorFrame {
  code: string;
  message: string;
  correlation_id: string;
}

// `DecisionRecord` (docs/DATA_CONTRACTS.md §7). Kept loose here rather than
// re-declaring every nested field: `lib/api-types.ts#DecisionOut` already
// owns that shape for the REST path, and `ResultBlock` narrows what it
// actually renders.
export type ResultFrame = Record<string, unknown>;

export interface SentinelChatSocketHandlers {
  onOpen?: () => void;
  // `backend/src/iam_sentinel_backend/ws/fanout.py`'s `started` event
  // (added alongside this phase per ADR 0022): the server-minted
  // `correlation_id`, echoed before any progress chunk so Cancel has
  // something to target.
  onStarted?: (correlationId: string) => void;
  onProgress?: (text: string) => void;
  onResult?: (decision: ResultFrame) => void;
  onError?: (error: ErrorFrame) => void;
  onClose?: (willReconnect: boolean) => void;
}

const RECONNECT_DELAY_MS = 1_000;
const HEARTBEAT_INTERVAL_MS = 25_000;

/**
 * Parses the SSE-flavored text block `backend/src/iam_sentinel_backend/
 * ws/protocol.py#encode_event` writes: `event: <name>\ndata: <payload>\n\n`.
 * Not real SSE (a bare `\n` inside `data`'s payload -- e.g. a multi-line
 * LLM chunk -- is NOT re-prefixed per line the way the SSE spec requires),
 * so this parses positionally rather than reusing an off-the-shelf SSE
 * parser: split on the first `\n` for the event name, then take
 * everything up to the trailing `\n\n` as the (possibly multi-line) data.
 */
export function parseServerFrame(raw: string): { event: string; data: string } | null {
  const match = /^event: ([^\n]+)\ndata: ([\s\S]*)\n\n$/.exec(raw);
  if (!match) return null;
  const [, event, data] = match;
  if (!event) return null;
  return { event, data: data ?? "" };
}

/**
 * Reconnecting WebSocket wrapper for `SentinelStream` (phase-01 §4). Fetches
 * a same-origin, single-use access token (ADR 0022) immediately before each
 * connection attempt rather than caching it across reconnects, since a
 * long-lived chat session can outlive the token's own short TTL.
 */
export class SentinelChatSocket {
  private socket: WebSocket | null = null;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private manuallyClosed = false;

  constructor(private readonly handlers: SentinelChatSocketHandlers) {}

  async connect(): Promise<void> {
    this.manuallyClosed = false;
    const token = await this.fetchToken();
    if (this.manuallyClosed) return;

    const url = new URL(getPublicEnv().NEXT_PUBLIC_WS_URL);
    url.searchParams.set("token", token);

    const socket = new WebSocket(url.toString());
    this.socket = socket;

    socket.onopen = () => {
      this.startHeartbeat();
      this.handlers.onOpen?.();
    };
    socket.onmessage = (event) => this.handleMessage(event);
    socket.onclose = () => this.handleClose();
    socket.onerror = () => {
      // Swallow: the browser also fires `close` right after `error` for a
      // failed handshake, and `handleClose` is what decides whether to
      // reconnect -- surfacing both would double-report the same failure.
    };
  }

  send(frame: { action: "chat"; query: ChatQuery } | { action: "cancel"; correlation_id: string } | { action: "ping" }): void {
    if (this.socket?.readyState === WebSocket.OPEN) {
      this.socket.send(JSON.stringify(frame));
    }
  }

  close(): void {
    this.manuallyClosed = true;
    this.stopHeartbeat();
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.socket?.close();
    this.socket = null;
  }

  private async fetchToken(): Promise<string> {
    const response = await fetch("/api/ws-token", { credentials: "same-origin" });
    const envelope = (await response.json()) as { ok: boolean; data?: { token: string } };
    if (!envelope.ok || !envelope.data) {
      throw new Error("Failed to mint a WebSocket session token.");
    }
    return envelope.data.token;
  }

  private handleMessage(event: MessageEvent<string>): void {
    const frame = parseServerFrame(event.data);
    if (!frame) return;

    switch (frame.event) {
      case "started": {
        const started = JSON.parse(frame.data) as { correlation_id: string };
        this.handlers.onStarted?.(started.correlation_id);
        break;
      }
      case "progress":
        this.handlers.onProgress?.(frame.data);
        break;
      case "result":
        this.handlers.onResult?.(JSON.parse(frame.data) as ResultFrame);
        break;
      case "error":
        this.handlers.onError?.(JSON.parse(frame.data) as ErrorFrame);
        break;
      case "pong":
        break;
      default:
        break;
    }
  }

  private handleClose(): void {
    this.stopHeartbeat();
    this.socket = null;
    const willReconnect = !this.manuallyClosed;
    this.handlers.onClose?.(willReconnect);
    if (willReconnect) {
      this.reconnectTimer = setTimeout(() => {
        void this.connect();
      }, RECONNECT_DELAY_MS);
    }
  }

  private startHeartbeat(): void {
    this.heartbeat = setInterval(() => this.send({ action: "ping" }), HEARTBEAT_INTERVAL_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeat) {
      clearInterval(this.heartbeat);
      this.heartbeat = null;
    }
  }
}
