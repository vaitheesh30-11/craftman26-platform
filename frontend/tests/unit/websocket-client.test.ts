import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { parseServerFrame, SentinelChatSocket } from "@/lib/websocket-client";

describe("parseServerFrame", () => {
  it("parses a single-line data payload", () => {
    expect(parseServerFrame("event: progress\ndata: thinking...\n\n")).toEqual({
      event: "progress",
      data: "thinking...",
    });
  });

  it("parses a JSON object payload", () => {
    expect(parseServerFrame('event: started\ndata: {"correlation_id": "c1"}\n\n')).toEqual({
      event: "started",
      data: '{"correlation_id": "c1"}',
    });
  });

  it("preserves embedded newlines in the data payload", () => {
    expect(parseServerFrame("event: progress\ndata: line one\nline two\n\n")).toEqual({
      event: "progress",
      data: "line one\nline two",
    });
  });

  it("returns null for a malformed frame", () => {
    expect(parseServerFrame("not a frame")).toBeNull();
  });
});

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static readonly OPEN = 1;
  static readonly CONNECTING = 0;

  readyState = FakeWebSocket.CONNECTING;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  sent: string[] = [];

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
    this.onclose?.();
  }

  triggerOpen() {
    this.readyState = FakeWebSocket.OPEN;
    this.onopen?.();
  }
}

describe("SentinelChatSocket reconnect", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ json: () => Promise.resolve({ ok: true, data: { token: "t" } }) }),
    );
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  it("reconnects within 2 seconds of an unexpected close", async () => {
    const onClose = vi.fn();
    const socket = new SentinelChatSocket({ onClose });
    await socket.connect();

    expect(FakeWebSocket.instances).toHaveLength(1);
    FakeWebSocket.instances[0]!.close();
    expect(onClose).toHaveBeenCalledWith(true);

    await vi.advanceTimersByTimeAsync(2_000);
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("does not reconnect after a manual close", async () => {
    const onClose = vi.fn();
    const socket = new SentinelChatSocket({ onClose });
    await socket.connect();

    socket.close();
    expect(FakeWebSocket.instances).toHaveLength(1);

    await vi.advanceTimersByTimeAsync(5_000);
    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("routes a started/progress/result sequence to the right handlers", async () => {
    const onStarted = vi.fn();
    const onProgress = vi.fn();
    const onResult = vi.fn();
    const socket = new SentinelChatSocket({ onStarted, onProgress, onResult });
    await socket.connect();

    const ws = FakeWebSocket.instances[0]!;
    ws.onmessage?.({ data: 'event: started\ndata: {"correlation_id": "c1"}\n\n' });
    ws.onmessage?.({ data: "event: progress\ndata: thinking...\n\n" });
    ws.onmessage?.({ data: 'event: result\ndata: {"decision_id": "d1"}\n\n' });

    expect(onStarted).toHaveBeenCalledWith("c1");
    expect(onProgress).toHaveBeenCalledWith("thinking...");
    expect(onResult).toHaveBeenCalledWith({ decision_id: "d1" });
  });
});
