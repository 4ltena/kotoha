# Overlay SP3 — Desktop Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development or executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** The overlay character drags with the mouse, wanders on its own along the taskbar, falls with gravity, and lands on the work-area bottom. Primary monitor only.

**Architecture:** Small moving window. The renderer owns logical window position, physics, and walking; `main.js` is a thin window+IPC shim. Pointer-aware click-through: mousemove is forwarded even while click-through, the renderer hit-tests the character and toggles interactivity. Pure logic (physics, walker, hit-test) is unit-tested with Vitest; window/drag/render are verified by running.

**Tech Stack:** Electron, three.js, @pixiv/three-vrm, Vitest. JavaScript (ESM renderer, CommonJS main).

## Global Constraints

- **Window model:** keep the existing small transparent frameless always-on-top window; movement/physics/drag reposition the OS window via IPC `setPosition`.
- **Click-through default on:** `setIgnoreMouseEvents(true, { forward: true })`; renderer toggles via IPC `setInteractive` only while the cursor is over the character.
- **Floor:** `workArea` bottom minus window height (character stands on the taskbar). Horizontal range `[workArea.x, workArea.x + workArea.width - winWidth]`.
- **Primary monitor only.** Multi-monitor roaming is out of scope.
- **Best-effort:** IPC/overlay failures must not crash; `getDisplay` falls back to a screen-size estimate.
- **SP2 coordination:** while `state === "speaking"`, suspend wandering and face front; expressions/mouth keep working.
- **Pure-logic units only get automated tests** (physics/walker/hit-test). Window/drag/render are manual.
- **Commit:** user's git config; English title; trailer after a blank line `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

## File Structure

- `overlay/main.js` (modify) — add IPC handlers `overlay:getDisplay`, `overlay:setPosition`, `overlay:setInteractive`.
- `overlay/preload.js` (modify) — expose `window.overlay = { getDisplay, setPosition, setInteractive }`.
- `overlay/renderer/physics.js` (new, pure) — gravity integration, floor clamp, throw velocity.
- `overlay/renderer/walker.js` (new, pure) — idle/walk state machine.
- `overlay/renderer/hit-test.js` (new, pure) — point-in-rect.
- `overlay/renderer/interaction.js` (new) — pointer wiring (hover/drag), throw samples.
- `overlay/renderer/main.js` (modify) — integrate position/physics/walker/drag, apply window position, face direction, SP2 coordination.
- `overlay/test/physics.test.js`, `walker.test.js`, `hit-test.test.js` (new).

---

### Task 1: Window IPC (main + preload)

**Files:** Modify `overlay/main.js`, `overlay/preload.js`.

**Interfaces produced:** `window.overlay.getDisplay()` → `{ workArea:{x,y,width,height}, bounds:{x,y,width,height} }`; `window.overlay.setPosition(x,y)`; `window.overlay.setInteractive(bool)`.

- [ ] **Step 1: add IPC handlers in `overlay/main.js`** — add `ipcMain` to the require, and register handlers inside `createWindow` after the window is created (so `win` is in scope). Insert after the `win.setIgnoreMouseEvents(...)` line:

```javascript
  const { ipcMain, screen } = require("electron");
  ipcMain.handle("overlay:getDisplay", () => {
    const d = screen.getPrimaryDisplay();
    return { workArea: d.workArea, bounds: win.getBounds() };
  });
  ipcMain.on("overlay:setPosition", (_e, x, y) => {
    if (win.isDestroyed()) return;
    win.setPosition(Math.round(x), Math.round(y));
  });
  ipcMain.on("overlay:setInteractive", (_e, interactive) => {
    if (win.isDestroyed()) return;
    win.setIgnoreMouseEvents(!interactive, { forward: true });
  });
```

> `screen` is already required at the top from SP1; the local re-require is harmless but prefer using the top-level `screen`. If `screen` is already in the top `require("electron")` destructure, drop it from the local line and keep only `ipcMain`.

- [ ] **Step 2: expose the API in `overlay/preload.js`** — replace the file contents with:

```javascript
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("overlay", {
  getDisplay: () => ipcRenderer.invoke("overlay:getDisplay"),
  setPosition: (x, y) => ipcRenderer.send("overlay:setPosition", x, y),
  setInteractive: (v) => ipcRenderer.send("overlay:setInteractive", v),
});
```

- [ ] **Step 3: manual smoke** — `npm run dev` + `npm run dev:app`. In devtools console, `await window.overlay.getDisplay()` returns the work area; `window.overlay.setPosition(100,100)` moves the window; `window.overlay.setInteractive(true)` then clicking the window no longer passes through.

- [ ] **Step 4: commit**

```bash
git add overlay/main.js overlay/preload.js
git commit -m "feat(overlay): add window IPC (getDisplay/setPosition/setInteractive)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: physics.js (gravity, floor, throw)

**Files:** Create `overlay/renderer/physics.js`, `overlay/test/physics.test.js`.

**Interfaces produced:** `step(state, dt, floorY) -> {x,y,vx,vy,grounded}`; `throwVelocity(samples) -> {vx,vy}`; constants `GRAVITY`, `GROUND_FRICTION`.

- [ ] **Step 1: write the failing test `overlay/test/physics.test.js`**

```javascript
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
  it("decays horizontal velocity while grounded", () => {
    const s = step({ x: 0, y: 1000, vx: 200, vy: 0, grounded: true }, 0.1, 1000);
    expect(Math.abs(s.vx)).toBeLessThan(200);
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
});
```

- [ ] **Step 2: run, verify it fails** — `cd overlay && npx vitest run test/physics.test.js` → FAIL (module missing).

- [ ] **Step 3: implement `overlay/renderer/physics.js`**

```javascript
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
```

- [ ] **Step 4: run, verify it passes** — `npx vitest run test/physics.test.js` → PASS.

- [ ] **Step 5: commit**

```bash
git add overlay/renderer/physics.js overlay/test/physics.test.js
git commit -m "feat(overlay): add physics (gravity, floor clamp, throw velocity)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: walker.js (idle/walk state machine)

**Files:** Create `overlay/renderer/walker.js`, `overlay/test/walker.test.js`.

**Interfaces produced:** `initialState() -> {mode,targetX,timer,facing}`; `update(state, x, dt, bounds, rng) -> {state, dx, facing}`; constants `WALK_SPEED`, `IDLE_MIN`, `IDLE_MAX`. `bounds = {minX, maxX}`. `rng` returns [0,1).

- [ ] **Step 1: write the failing test `overlay/test/walker.test.js`**

```javascript
import { describe, it, expect } from "vitest";
import { initialState, update, WALK_SPEED } from "../renderer/walker.js";

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
});
```

- [ ] **Step 2: run, verify it fails** — `npx vitest run test/walker.test.js` → FAIL.

- [ ] **Step 3: implement `overlay/renderer/walker.js`**

```javascript
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
```

- [ ] **Step 4: run, verify it passes** — `npx vitest run test/walker.test.js` → PASS.

- [ ] **Step 5: commit**

```bash
git add overlay/renderer/walker.js overlay/test/walker.test.js
git commit -m "feat(overlay): add walker idle/walk state machine

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: hit-test.js (point in rect)

**Files:** Create `overlay/renderer/hit-test.js`, `overlay/test/hit-test.test.js`.

**Interfaces produced:** `isOverRect(px, py, rect) -> boolean`, `rect = {x,y,w,h}`.

- [ ] **Step 1: write the failing test `overlay/test/hit-test.test.js`**

```javascript
import { describe, it, expect } from "vitest";
import { isOverRect } from "../renderer/hit-test.js";

const rect = { x: 10, y: 20, w: 100, h: 200 };

describe("isOverRect", () => {
  it("is true inside", () => {
    expect(isOverRect(50, 100, rect)).toBe(true);
  });
  it("is true on the edges", () => {
    expect(isOverRect(10, 20, rect)).toBe(true);
    expect(isOverRect(110, 220, rect)).toBe(true);
  });
  it("is false outside", () => {
    expect(isOverRect(5, 100, rect)).toBe(false);
    expect(isOverRect(50, 500, rect)).toBe(false);
  });
});
```

- [ ] **Step 2: run, verify it fails** — `npx vitest run test/hit-test.test.js` → FAIL.

- [ ] **Step 3: implement `overlay/renderer/hit-test.js`**

```javascript
export function isOverRect(px, py, rect) {
  return (
    px >= rect.x &&
    px <= rect.x + rect.w &&
    py >= rect.y &&
    py <= rect.y + rect.h
  );
}
```

- [ ] **Step 4: run, verify it passes** — `npx vitest run test/hit-test.test.js` → PASS.

- [ ] **Step 5: commit**

```bash
git add overlay/renderer/hit-test.js overlay/test/hit-test.test.js
git commit -m "feat(overlay): add point-in-rect hit test

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: interaction.js (pointer wiring)

**Files:** Create `overlay/renderer/interaction.js`.

**Interfaces produced:** `installInteraction(cb)` where `cb = { isOverCharacter(clientX,clientY)->bool, onHover(over), onDragStart(), onDragMove(dxScreen,dyScreen), onDragEnd(throwVel) }`. Records drag samples and computes the throw velocity with `throwVelocity`.

- [ ] **Step 1: implement `overlay/renderer/interaction.js`**

```javascript
import { throwVelocity } from "./physics.js";

// Wires window mouse events to drag/hover callbacks. The window forwards
// mousemove even while click-through (setIgnoreMouseEvents forward:true),
// so hover detection keeps working when not interactive.
export function installInteraction(cb) {
  let over = false;
  let dragging = false;
  let last = null;
  let samples = [];

  window.addEventListener("mousemove", (e) => {
    const nowOver = cb.isOverCharacter(e.clientX, e.clientY);
    if (nowOver !== over) {
      over = nowOver;
      cb.onHover(over);
    }
    if (dragging) {
      const dx = e.screenX - last.x;
      const dy = e.screenY - last.y;
      last = { x: e.screenX, y: e.screenY };
      samples.push({ x: e.screenX, y: e.screenY, t: performance.now() });
      if (samples.length > 6) samples.shift();
      cb.onDragMove(dx, dy);
    }
  });

  window.addEventListener("mousedown", (e) => {
    if (!cb.isOverCharacter(e.clientX, e.clientY)) return;
    dragging = true;
    last = { x: e.screenX, y: e.screenY };
    samples = [{ x: e.screenX, y: e.screenY, t: performance.now() }];
    cb.onDragStart();
  });

  window.addEventListener("mouseup", () => {
    if (!dragging) return;
    dragging = false;
    cb.onDragEnd(throwVelocity(samples));
    samples = [];
  });
}
```

- [ ] **Step 2: commit** (no separate test; covered by manual run in Task 6)

```bash
git add overlay/renderer/interaction.js
git commit -m "feat(overlay): add pointer interaction wiring (hover/drag/throw)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: integrate into renderer/main.js

**Files:** Modify `overlay/renderer/main.js`.

**Interfaces consumed:** Tasks 1–5. Produces the running behavior: drag, wander, fall, land, click-through toggle, SP2 coordination.

- [ ] **Step 1: replace `overlay/renderer/main.js` with the integrated version**

```javascript
import * as THREE from "three";
import { loadVRM, updateIdle } from "./vrm.js";
import { connect } from "./ws-client.js";
import { mergeConfig } from "./config.js";
import { installMockInjector } from "./mock-injector.js";
import * as physics from "./physics.js";
import * as walker from "./walker.js";
import { isOverRect } from "./hit-test.js";
import { installInteraction } from "./interaction.js";

const app = document.getElementById("app");
const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
renderer.setClearColor(0x000000, 0);
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);
app.appendChild(renderer.domElement);

const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(30, window.innerWidth / window.innerHeight, 0.1, 20);
camera.position.set(0, 1.3, 2.2);
camera.lookAt(0, 1.2, 0);
scene.add(new THREE.AmbientLight(0xffffff, 1.0));
const dir = new THREE.DirectionalLight(0xffffff, 1.0);
dir.position.set(1, 2, 2);
scene.add(dir);

let vrm = null;
let placeholder = null;
loadVRM(scene, "../assets/sample.vrm")
  .then((v) => { vrm = v; })
  .catch((err) => {
    console.error(err.message);
    placeholder = new THREE.Mesh(
      new THREE.BoxGeometry(0.4, 0.4, 0.4),
      new THREE.MeshStandardMaterial({ color: 0x66ccff })
    );
    placeholder.position.set(0, 1.2, 0);
    scene.add(placeholder);
  });

// --- SP2 state/mouth ---
const cfg = mergeConfig({});
let currentState = "idle";
let mouthTarget = 0;
connect(cfg.wsUrl, { onState: (v) => { currentState = v; }, onMouth: (l) => { mouthTarget = l; } });
installMockInjector({ onState: (v) => { currentState = v; }, onMouth: (l) => { mouthTarget = l; } });

// --- SP3 desktop interaction ---
const WIN_W = window.innerWidth;
const WIN_H = window.innerHeight;
const pos = { x: 0, y: 0, vx: 0, vy: 0, grounded: true };
let walkState = walker.initialState();
let facing = 1;
let dragging = false;
const bounds = { minX: 0, maxX: 0, floorY: 0 };

async function initBounds() {
  let disp;
  try {
    disp = await window.overlay.getDisplay();
  } catch {
    disp = { workArea: { x: 0, y: 0, width: screen.width, height: screen.height }, bounds: { x: 0, y: 0 } };
  }
  const wa = disp.workArea;
  bounds.minX = wa.x;
  bounds.maxX = wa.x + wa.width - WIN_W;
  bounds.floorY = wa.y + wa.height - WIN_H;
  pos.x = disp.bounds ? disp.bounds.x : bounds.maxX;
  pos.y = bounds.floorY;
}
initBounds();

// Character hit region within the window (centered column where the VRM is).
function characterRect() {
  const w = WIN_W * 0.6;
  const h = WIN_H * 0.9;
  return { x: (WIN_W - w) / 2, y: WIN_H - h, w, h };
}

installInteraction({
  isOverCharacter: (cx, cy) => isOverRect(cx, cy, characterRect()),
  onHover: (over) => window.overlay && window.overlay.setInteractive(over),
  onDragStart: () => { dragging = true; },
  onDragMove: (dx, dy) => {
    pos.x = Math.max(bounds.minX, Math.min(bounds.maxX, pos.x + dx));
    pos.y = Math.min(bounds.floorY, pos.y + dy);
  },
  onDragEnd: (v) => {
    dragging = false;
    pos.vx = v.vx;
    pos.vy = v.vy;
    pos.grounded = false;
  },
});

const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = Math.min(0.05, clock.getDelta());

  if (!dragging) {
    if (pos.grounded && currentState !== "speaking") {
      const w = walker.update(walkState, pos.x, dt, bounds, Math.random);
      walkState = w.state;
      facing = w.facing;
      pos.x = Math.max(bounds.minX, Math.min(bounds.maxX, pos.x + w.dx));
    }
    const n = physics.step(pos, dt, bounds.floorY);
    pos.x = Math.max(bounds.minX, Math.min(bounds.maxX, n.x));
    pos.y = n.y;
    pos.vx = n.vx;
    pos.vy = n.vy;
    pos.grounded = n.grounded;
  }
  if (window.overlay) window.overlay.setPosition(pos.x, pos.y);

  if (vrm) {
    updateIdle(vrm, clock.elapsedTime);
    if (vrm.scene) vrm.scene.rotation.y = facing >= 0 ? 0 : Math.PI;
    if (vrm.expressionManager) {
      const open = currentState === "speaking" ? mouthTarget : 0;
      vrm.expressionManager.setValue("aa", open);
    }
    vrm.update(dt);
  }
  if (placeholder) placeholder.rotation.y += dt;
  renderer.render(scene, camera);
}
animate();

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
```

- [ ] **Step 2: full unit suite** — `cd overlay && npm test` → all green (config, mappings, ws-client, physics, walker, hit-test).

- [ ] **Step 3: manual run** — place a VRM at `assets/sample.vrm`, then `npm run dev` + `npm run dev:app`. Verify: the character stands on the taskbar and walks left/right on its own; hovering the character makes it grabbable while the rest stays click-through; dragging moves it; releasing drops it with gravity and a throw; with SP2 running, speaking stops the wandering and drives the mouth.

- [ ] **Step 4: commit**

```bash
git add overlay/renderer/main.js
git commit -m "feat(overlay): wire drag, wander, physics, and click-through toggle

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Completion check

- [ ] `cd overlay && npm test` — config, mappings, ws-client, physics, walker, hit-test all pass.
- [ ] Manual: character wanders on the taskbar, is draggable only over its body, falls and lands when released, and respects SP2 `speaking`.

## Acceptance (spec)

The character stands on the primary work-area bottom and wanders, can be grabbed and dragged, falls with gravity and lands on release, throws with the drag velocity, passes clicks through except over its body, and pauses wandering while speaking.
