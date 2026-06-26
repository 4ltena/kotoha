export const GRAVITY = 2600;        // px/s^2
export const GROUND_FRICTION = 6;   // higher = stops sooner

// Integrate one frame. Position is the window top-left in screen px.
export function step(state, dt, floorY) {
  let { x, y, vx, vy } = state;
  vy += GRAVITY * dt;
  x += vx * dt;
  y += vy * dt;
  let grounded = false;
  if (y >= floorY) {
    y = floorY;
    vy = 0;
    grounded = true;
    vx -= vx * Math.min(1, GROUND_FRICTION * dt);
    if (Math.abs(vx) < 1) vx = 0;
  }
  return { x, y, vx, vy, grounded };
}

// Velocity (px/s) from recorded drag samples [{x,y,t(ms)}].
export function throwVelocity(samples) {
  if (!samples || samples.length < 2) return { vx: 0, vy: 0 };
  const a = samples[0];
  const b = samples[samples.length - 1];
  const dt = (b.t - a.t) / 1000;
  if (dt <= 0) return { vx: 0, vy: 0 };
  return { vx: (b.x - a.x) / dt, vy: (b.y - a.y) / dt };
}
