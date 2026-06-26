import { describe, it, expect } from "vitest";
import { step, throwVelocity, GRAVITY } from "../renderer/physics.js";

describe("step", () => {
  it("applies gravity and falls when above floor", () => {
    const s = step({ x: 0, y: 0, vx: 0, vy: 0, grounded: false }, 0.1, 1000);
    expect(s.vy).toBeCloseTo(GRAVITY * 0.1, 3);
    expect(s.y).toBeGreaterThan(0);
    expect(s.grounded).toBe(false);
  });
  it("clamps to floor and grounds", () => {
    const s = step({ x: 0, y: 990, vx: 0, vy: 500, grounded: false }, 0.1, 1000);
    expect(s.y).toBe(1000);
    expect(s.vy).toBe(0);
    expect(s.grounded).toBe(true);
  });
  it("decays horizontal velocity while grounded (positive)", () => {
    const s = step({ x: 0, y: 1000, vx: 200, vy: 0, grounded: true }, 0.1, 1000);
    expect(s.vx).toBeCloseTo(80, 1);
  });
  it("decays horizontal velocity while grounded (negative)", () => {
    const s = step({ x: 0, y: 1000, vx: -200, vy: 0, grounded: true }, 0.1, 1000);
    expect(s.vx).toBeCloseTo(-80, 1);
  });
});

describe("throwVelocity", () => {
  it("computes px/s from first and last sample", () => {
    const v = throwVelocity([
      { x: 0, y: 0, t: 0 },
      { x: 30, y: -10, t: 100 },
    ]);
    expect(v.vx).toBeCloseTo(300, 3);
    expect(v.vy).toBeCloseTo(-100, 3);
  });
  it("returns zero for fewer than two samples", () => {
    expect(throwVelocity([{ x: 0, y: 0, t: 0 }])).toEqual({ vx: 0, vy: 0 });
  });
  it("returns zero when dt is non-positive", () => {
    expect(throwVelocity([{ x: 0, y: 0, t: 5 }, { x: 9, y: 9, t: 5 }])).toEqual({ vx: 0, vy: 0 });
  });
  it("uses first and last sample only (ignores middle)", () => {
    const v = throwVelocity([
      { x: 0, y: 0, t: 0 },
      { x: 9999, y: 9999, t: 50 },
      { x: 30, y: -10, t: 100 },
    ]);
    expect(v.vx).toBeCloseTo(300, 0);
    expect(v.vy).toBeCloseTo(-100, 0);
  });
});
