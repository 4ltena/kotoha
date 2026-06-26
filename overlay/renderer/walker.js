export const WALK_SPEED = 90;   // px/s
export const IDLE_MIN = 2;      // s
export const IDLE_MAX = 6;      // s

export function initialState() {
  return { mode: "idle", targetX: 0, timer: 1, facing: 1 };
}

// Returns { state, dx, facing }. dx is the horizontal step to apply this frame.
export function update(state, x, dt, bounds, rng) {
  let { mode, targetX, timer, facing } = state;
  let dx = 0;

  if (mode === "walk") {
    const remaining = targetX - x;
    const stepLen = WALK_SPEED * dt;
    if (Math.abs(remaining) <= stepLen) {
      dx = remaining;
      facing = remaining < 0 ? -1 : 1;
      mode = "idle";
      timer = IDLE_MIN + rng() * (IDLE_MAX - IDLE_MIN);
    } else {
      const dir = remaining >= 0 ? 1 : -1;
      dx = dir * stepLen;
      facing = dir;
    }
  } else {
    timer -= dt;
    if (timer <= 0) {
      targetX = bounds.minX + rng() * (bounds.maxX - bounds.minX);
      mode = "walk";
    }
  }

  return { state: { mode, targetX, timer, facing }, dx, facing };
}
