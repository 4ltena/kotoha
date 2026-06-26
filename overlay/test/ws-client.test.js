import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { parseMessage, nextBackoff, connect } from "../renderer/ws-client.js";

describe("parseMessage", () => {
  it("parses a state frame", () => {
    expect(parseMessage('{"type":"state","value":"speaking"}'))
      .toEqual({ type: "state", value: "speaking" });
  });
  it("parses and clamps a mouth frame", () => {
    expect(parseMessage('{"type":"mouth","value":2}'))
      .toEqual({ type: "mouth", value: 1 });
  });
  it("rejects an unknown state", () => {
    expect(parseMessage('{"type":"state","value":"nope"}')).toBeNull();
  });
  it("returns null on malformed JSON", () => {
    expect(parseMessage("not json")).toBeNull();
  });
  it("returns null on unknown type", () => {
    expect(parseMessage('{"type":"x","value":1}')).toBeNull();
  });
  it("returns null for mouth frame with missing value", () => {
    expect(parseMessage('{"type":"mouth"}')).toBeNull();
  });
  it("returns null for mouth frame with non-numeric value", () => {
    expect(parseMessage('{"type":"mouth","value":"x"}')).toBeNull();
  });
});

describe("nextBackoff", () => {
  it("grows exponentially and caps at 10s", () => {
    expect(nextBackoff(0)).toBe(1000);
    expect(nextBackoff(1)).toBe(2000);
    expect(nextBackoff(20)).toBe(10000);
  });
});

describe("connect", () => {
  let instances;
  let OriginalWebSocket;

  class MockWebSocket {
    constructor(url) {
      this.url = url;
      this.onopen = null;
      this.onclose = null;
      this.onmessage = null;
      this.onerror = null;
      instances.push(this);
    }
    close() {}
  }

  beforeEach(() => {
    instances = [];
    OriginalWebSocket = global.WebSocket;
    global.WebSocket = MockWebSocket;
    vi.useFakeTimers();
  });

  afterEach(() => {
    global.WebSocket = OriginalWebSocket;
    vi.useRealTimers();
  });

  it("calls onState('idle') and reconnects after nextBackoff(0) on close", () => {
    const handlers = { onState: vi.fn(), onMouth: vi.fn() };
    connect("ws://test", handlers);
    expect(instances.length).toBe(1);
    instances[0].onclose();
    expect(handlers.onState).toHaveBeenCalledWith("idle");
    vi.advanceTimersByTime(nextBackoff(0));
    expect(instances.length).toBe(2);
  });

  it("stop() before close prevents reconnect", () => {
    const handlers = { onState: vi.fn(), onMouth: vi.fn() };
    const stop = connect("ws://test", handlers);
    expect(instances.length).toBe(1);
    stop();
    instances[0].onclose?.();
    vi.advanceTimersByTime(nextBackoff(0));
    expect(instances.length).toBe(1);
  });

  it("after onopen then onclose, reconnect delay is 1000ms (attempt reset)", () => {
    const handlers = { onState: vi.fn(), onMouth: vi.fn() };
    connect("ws://test", handlers);
    instances[0].onopen();
    instances[0].onclose();
    vi.advanceTimersByTime(1000);
    expect(instances.length).toBe(2);
  });
});
