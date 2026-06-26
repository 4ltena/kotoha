import { describe, it, expect } from "vitest";
import { initialState, update, WALK_SPEED, IDLE_MIN, IDLE_MAX } from "../renderer/walker.js";

const bounds = { minX: 0, maxX: 1000 };

describe("walker", () => {
  it("starts idle", () => {
    expect(initialState().mode).toBe("idle");
  });
  it("picks a walk target in bounds when the idle timer elapses", () => {
    const s = { mode: "idle", targetX: 0, timer: 0.01, facing: 1 };
    const r = update(s, 500, 0.1, bounds, () => 0.5);
    expect(r.state.mode).toBe("walk");
    expect(r.state.targetX).toBeGreaterThanOrEqual(bounds.minX);
    expect(r.state.targetX).toBeLessThanOrEqual(bounds.maxX);
    expect(r.state.targetX).toBeCloseTo(500, 3); // 0.5 * (max-min) + min
  });
  it("moves toward the target and faces that way", () => {
    const s = { mode: "walk", targetX: 800, timer: 0, facing: -1 };
    const r = update(s, 500, 0.1, bounds, () => 0);
    expect(r.dx).toBeCloseTo(WALK_SPEED * 0.1, 3);
    expect(r.facing).toBe(1);
    expect(r.state.mode).toBe("walk");
  });
  it("returns to idle when it reaches the target", () => {
    const s = { mode: "walk", targetX: 503, timer: 0, facing: 1 };
    const r = update(s, 500, 0.1, bounds, () => 0.5); // step (9px) > remaining (3px)
    expect(r.dx).toBeCloseTo(3, 3);
    expect(r.state.mode).toBe("idle");
    expect(r.state.timer).toBeGreaterThan(0);
  });
  it("stays idle while the timer remains", () => {
    const s = { mode: "idle", targetX: 0, timer: 5, facing: 1 };
    const r = update(s, 500, 0.1, bounds, () => 0.5);
    expect(r.state.mode).toBe("idle");
    expect(r.dx).toBe(0);
  });
  it("leftward walk produces negative dx and facing -1", () => {
    const s = { mode: "walk", targetX: 200, timer: 0, facing: 1 };
    const r = update(s, 500, 0.1, bounds, () => 0);
    expect(r.dx).toBeCloseTo(-WALK_SPEED * 0.1, 3);
    expect(r.facing).toBe(-1);
  });
  it("leftward arrival sets facing -1 and transitions to idle", () => {
    const s = { mode: "walk", targetX: 497, timer: 0, facing: 1 };
    const r = update(s, 500, 0.1, bounds, () => 0.5);
    expect(r.dx).toBeCloseTo(-3, 3);
    expect(r.facing).toBe(-1);
    expect(r.state.facing).toBe(-1);
    expect(r.state.mode).toBe("idle");
  });
  it("timer on arrival is within IDLE_MIN..IDLE_MAX", () => {
    const s = { mode: "walk", targetX: 497, timer: 0, facing: 1 };
    // use rng=()=>0.5 so timer = IDLE_MIN + 0.5*(IDLE_MAX-IDLE_MIN)
    const r = update(s, 500, 0.1, bounds, () => 0.5);
    expect(r.state.timer).toBeGreaterThanOrEqual(IDLE_MIN);
    expect(r.state.timer).toBeLessThanOrEqual(IDLE_MAX);
  });
});
