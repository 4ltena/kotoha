import { describe, it, expect } from "vitest";
import { mergeConfig, DEFAULTS } from "../renderer/config.js";

describe("mergeConfig", () => {
  it("returns defaults for empty input", () => {
    expect(mergeConfig({})).toEqual(DEFAULTS);
  });
  it("overrides only provided keys", () => {
    const c = mergeConfig({ wsUrl: "ws://x:1/ws", fps: 60 });
    expect(c.wsUrl).toBe("ws://x:1/ws");
    expect(c.fps).toBe(60);
    expect(c.vrmUrl).toBe(DEFAULTS.vrmUrl);
  });
  it("ignores undefined values", () => {
    expect(mergeConfig({ wsUrl: undefined }).wsUrl).toBe(DEFAULTS.wsUrl);
  });
  it("ignores null values", () => {
    expect(mergeConfig({ wsUrl: null }).wsUrl).toBe(DEFAULTS.wsUrl);
  });
});
