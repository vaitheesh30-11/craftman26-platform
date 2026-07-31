import { create } from "zustand";

import {
  SentinelChatSocket,
  type ChatQuery,
  type ErrorFrame,
  type ResultFrame,
} from "@/lib/websocket-client";

export type ConnectionStatus = "idle" | "connecting" | "open" | "closed";

export interface UserEntry {
  kind: "user";
  id: string;
  text: string;
}

export interface TurnEntry {
  kind: "turn";
  id: string;
  correlationId: string | null;
  progressLines: string[];
  state: "streaming" | "canceled" | "errored" | "done";
  result?: ResultFrame;
  error?: ErrorFrame;
}

export type TranscriptEntry = UserEntry | TurnEntry;

interface ChatSessionState {
  status: ConnectionStatus;
  transcript: TranscriptEntry[];
  activeTurnId: string | null;
  connect: () => void;
  disconnect: () => void;
  sendQuery: (query: ChatQuery) => void;
  cancelActive: () => void;
}

function newId(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : Math.random().toString(36).slice(2);
}

// Socket instance lives outside reactive state deliberately -- it is a
// side-effecting handle, not serializable UI state, and putting it in
// `set()` would trigger a re-render on every internal reconnect.
let socket: SentinelChatSocket | null = null;

export const useChatSession = create<ChatSessionState>((set, get) => ({
  status: "idle",
  transcript: [],
  activeTurnId: null,

  connect: () => {
    if (socket) return;
    set({ status: "connecting" });
    socket = new SentinelChatSocket({
      onOpen: () => set({ status: "open" }),
      onStarted: (correlationId) => {
        const activeTurnId = get().activeTurnId;
        if (!activeTurnId) return;
        set({
          transcript: get().transcript.map((entry) =>
            entry.kind === "turn" && entry.id === activeTurnId
              ? { ...entry, correlationId }
              : entry,
          ),
        });
      },
      onProgress: (text) => {
        const activeTurnId = get().activeTurnId;
        if (!activeTurnId) return;
        set({
          transcript: get().transcript.map((entry) =>
            entry.kind === "turn" && entry.id === activeTurnId
              ? { ...entry, progressLines: [...entry.progressLines, text] }
              : entry,
          ),
        });
      },
      onResult: (result) => {
        const activeTurnId = get().activeTurnId;
        if (!activeTurnId) return;
        set({
          activeTurnId: null,
          transcript: get().transcript.map((entry) =>
            entry.kind === "turn" && entry.id === activeTurnId
              ? { ...entry, state: "done" as const, result }
              : entry,
          ),
        });
      },
      onError: (error) => {
        const activeTurnId = get().activeTurnId;
        if (!activeTurnId) return;
        const state = error.code === "CANCELED" ? ("canceled" as const) : ("errored" as const);
        set({
          activeTurnId: null,
          transcript: get().transcript.map((entry) =>
            entry.kind === "turn" && entry.id === activeTurnId ? { ...entry, state, error } : entry,
          ),
        });
      },
      onClose: (willReconnect) => set({ status: willReconnect ? "connecting" : "closed" }),
    });
    void socket.connect();
  },

  disconnect: () => {
    socket?.close();
    socket = null;
    set({ status: "closed" });
  },

  sendQuery: (query) => {
    const turnId = newId();
    set((state) => ({
      activeTurnId: turnId,
      transcript: [
        ...state.transcript,
        { kind: "user", id: newId(), text: query.query_text },
        { kind: "turn", id: turnId, correlationId: null, progressLines: [], state: "streaming" },
      ],
    }));
    socket?.send({ action: "chat", query });
  },

  cancelActive: () => {
    const activeTurn = get().transcript.find(
      (entry): entry is TurnEntry => entry.kind === "turn" && entry.id === get().activeTurnId,
    );
    if (!activeTurn?.correlationId) return;
    socket?.send({ action: "cancel", correlation_id: activeTurn.correlationId });
  },
}));

// Test-only escape hatch: Vitest specs need to reset the module-level
// `socket` singleton between cases without reaching into closures.
export function __resetChatSocketForTests(): void {
  socket = null;
}
