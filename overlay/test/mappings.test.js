import { describe, it, expect } from "vitest";
import { amplitudeToMouth, isValidState } from "../renderer/mappings.js";

describe("amplitudeToMouth", () => {
  it("clamps to [0,1]", () => {
    expect(amplitudeToMouth(-0.5)).toBe(0);
    expect(amplitudeToMouth(2)).toBe(1);
    expect(amplitudeToMouth(0.4)).toBeCloseTo(0.4, 5);
  });
  it("treats non-finite as 0", () => {
    expect(amplitudeToMouth(NaN)).toBe(0);
  });
});

describe("isValidState", () => {
  it("accepts the four states", () => {
    for (const s of ["idle", "listening", "thinking", "speaking"]) {
      expect(isValidState(s)).toBe(true);
    }
  });
  it("rejects others", () => {
    expect(isValidState("dancing")).toBe(false);
  });
});
