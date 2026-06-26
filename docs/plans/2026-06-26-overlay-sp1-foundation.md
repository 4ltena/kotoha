# Overlay SP1 — Foundation (Electron + three-vrm) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A transparent, always-on-top, click-through desktop window that renders a VRM character (idle) and reflects Kotoha's state + lip-sync by consuming the SP2 WebSocket — runnable standalone (without Python).

**Architecture:** A standalone Electron app under `overlay/`. The main process creates a frameless transparent always-on-top click-through `BrowserWindow`; the renderer uses three.js + `@pixiv/three-vrm` (bundled by Vite) to draw a sample VRM with idle motion. A small WebSocket client connects to the SP2 bridge (`ws://127.0.0.1:8770/ws`) and maps `state`/`mouth` events to expressions. Pure logic (config, mappings, WS message parsing, reconnect backoff) is unit-tested with Vitest; window/render behavior is verified by running.

**Tech Stack:** Node.js 18+, Electron, Vite, three.js, `@pixiv/three-vrm`, Vitest. JavaScript (ESM).

## Global Constraints

- **Standalone-runnable:** SP1 must run and show an idle character WITHOUT Python/SP2 (WS simply stays disconnected; a mock injector drives `state`/`mouth` for local verification).
- **Window:** transparent, frameless, always-on-top, `skipTaskbar`, click-through by default (`setIgnoreMouseEvents(true, {forward:true})`). Must not block desktop interaction.
- **WS contract (consumed, from SP2 spec §4.5):** server→client JSON `{"type":"state","value":"idle|listening|thinking|speaking"}` and `{"type":"mouth","value":<0.0–1.0>}`. Default URL `ws://127.0.0.1:8770/ws` (configurable).
- **Best-effort:** overlay must tolerate WS absence/disconnect (retry with backoff; fall back to idle). VRM load failure logs clearly.
- **Placement:** `overlay/` is a separate Node project (its own `package.json`), kept out of the Python package `kotoha/`.
- **Toolchain note:** exact dependency versions are pinned at first `npm install` (use current stable: Electron ≥30, three ≥0.160 with matching `@pixiv/three-vrm` ≥3, Vite ≥5, Vitest ≥1). Window/render tasks are verified by `npm run dev` and visual inspection; only pure-logic tasks carry automated tests.
- **three-vrm v3 API anchors:** load via `GLTFLoader` + `loader.register((parser) => new VRMLoaderPlugin(parser))`, then `const vrm = gltf.userData.vrm`; per-frame `vrm.update(delta)`; expressions via `vrm.expressionManager.setValue(name, weight)` then `vrm.expressionManager.update()` (names: `"aa"` mouth-open, `"blink"`). For VRM0 models call `VRMUtils.rotateVRM0(vrm)` once after load.
- **Commit:** author/committer = the user's git config; commit title (line 1) in English; trailer after a blank line: `Co-Authored-By: Claude <noreply@anthropic.com>`.

---

## File Structure

- `overlay/package.json` — Node project + scripts (`dev`, `build`, `start`, `test`).
- `overlay/vite.config.js` — Vite config (root = `renderer/`, build to `dist/`).
- `overlay/main.js` — Electron main (CommonJS): create the window, load renderer.
- `overlay/preload.js` — minimal preload (contextIsolation-safe; exposes nothing privileged for SP1).
- `overlay/renderer/index.html` — renderer entry HTML (transparent body).
- `overlay/renderer/main.js` — three.js scene bootstrap + render loop.
- `overlay/renderer/vrm.js` — VRM load + idle (blink/sway) helpers.
- `overlay/renderer/config.js` — load/merge overlay config (pure).
- `overlay/renderer/mappings.js` — `stateToTarget` / `amplitudeToMouth` (pure).
- `overlay/renderer/ws-client.js` — WS connect + `parseMessage` + reconnect backoff (parse/backoff pure).
- `overlay/renderer/mock-injector.js` — keyboard-driven state/mouth for standalone verification.
- `overlay/config.json` — defaults (vrm path, window size/pos, ws url, fps).
- `overlay/assets/` — sample `.vrm` (placeholder; swapped later).
- `overlay/test/*.test.js` — Vitest unit tests for pure modules.
- `overlay/.gitignore` — `node_modules/`, `dist/`.

> The sample VRM is a placeholder; do not commit a large binary if licensing is unclear — instead document where to drop `overlay/assets/sample.vrm` and have the loader show a clear message if missing.

---

### Task 1: Electron + Vite project scaffold

**Files:**
- Create: `overlay/package.json`, `overlay/vite.config.js`, `overlay/.gitignore`, `overlay/renderer/index.html`, `overlay/renderer/main.js` (stub), `overlay/main.js`, `overlay/preload.js`

**Interfaces:**
- Produces: runnable `npm run dev` (Vite serves `renderer/`, Electron opens it) and `npm run build` (Vite builds to `dist/`). Renderer entry is `renderer/main.js`.

- [ ] **Step 1: Create `overlay/package.json`**

```json
{
  "name": "kotoha-overlay",
  "version": "0.1.0",
  "description": "Kotoha desktop overlay (VRM character)",
  "private": true,
  "main": "main.js",
  "scripts": {
    "dev": "vite",
    "dev:app": "electron . --dev",
    "build": "vite build",
    "start": "electron .",
    "test": "vitest run --config vitest.config.js"
  },
  "devDependencies": {
    "electron": "^30.0.0",
    "vite": "^5.0.0",
    "vitest": "^1.0.0"
  },
  "dependencies": {
    "three": "^0.160.0",
    "@pixiv/three-vrm": "^3.0.0"
  }
}
```

- [ ] **Step 2: Create `overlay/vite.config.js`**

```javascript
import { defineConfig } from "vite";

// renderer/ is the web root; build emits to ../dist for Electron to load in prod.
export default defineConfig({
  root: "renderer",
  base: "./",
  build: { outDir: "../dist", emptyOutDir: true },
  server: { port: 5273 },
});
```

- [ ] **Step 3: Create `overlay/.gitignore`**

```
node_modules/
dist/
```

- [ ] **Step 4: Create `overlay/renderer/index.html`**

```html
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      html, body { margin: 0; height: 100%; background: transparent; overflow: hidden; }
      #app { width: 100vw; height: 100vh; }
    </style>
  </head>
  <body>
    <div id="app"></div>
    <script type="module" src="./main.js"></script>
  </body>
</html>
```

- [ ] **Step 5: Create `overlay/renderer/main.js` (stub for now)**

```javascript
// Renderer entry. Filled in by later tasks (three.js scene, VRM, WS).
console.log("kotoha overlay renderer booting");
```

- [ ] **Step 6: Create `overlay/main.js` (Electron main, CommonJS)**

```javascript
const { app, BrowserWindow } = require("electron");
const path = require("node:path");

const DEV_URL = "http://localhost:5273";

function createWindow() {
  const win = new BrowserWindow({
    width: 400,
    height: 600,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  // dev は --dev フラグ(シェル非依存)で切替。OVERLAY_DEV=1 も後方互換で受ける。
  const isDev = process.argv.includes("--dev") || process.env.OVERLAY_DEV === "1";
  if (isDev) {
    win.loadURL(DEV_URL);
  } else {
    win.loadFile(path.join(__dirname, "dist", "index.html"));
  }
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});
```

- [ ] **Step 7: Create `overlay/preload.js`**

```javascript
// SP1 exposes nothing privileged to the renderer; kept for contextIsolation hygiene.
```

- [ ] **Step 8: Install and smoke-run**

Run:
```bash
cd overlay && npm install
# Dev: in one shell `npm run dev`; in another `npm run dev:app`
```
Expected: an Electron window opens showing a blank page; console logs "kotoha overlay renderer booting". (No transparency yet — that's Task 2.)

- [ ] **Step 9: Commit**

```bash
git add overlay/package.json overlay/vite.config.js overlay/.gitignore overlay/main.js overlay/preload.js overlay/renderer/index.html overlay/renderer/main.js
git commit -m "feat(overlay): scaffold Electron + Vite project

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: Transparent, frameless, always-on-top, click-through window

**Files:**
- Modify: `overlay/main.js`

**Interfaces:**
- Produces: a window that is transparent, frameless, always-on-top, skips the taskbar, and is click-through (mouse events pass to the desktop).

- [ ] **Step 1: Replace the `BrowserWindow` construction in `overlay/main.js`**

Replace the `const win = new BrowserWindow({...})` block with:
```javascript
  const win = new BrowserWindow({
    width: 400,
    height: 600,
    transparent: true,
    frame: false,
    resizable: false,
    hasShadow: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setAlwaysOnTop(true, "screen-saver");
  win.setIgnoreMouseEvents(true, { forward: true }); // click-through (SP1 default)
```

- [ ] **Step 2: Position bottom-right** — after `createWindow`'s window creation, before load, add:
```javascript
  const { screen } = require("electron");
  const wa = screen.getPrimaryDisplay().workAreaSize;
  win.setPosition(wa.width - 400 - 20, wa.height - 600 - 20);
```

- [ ] **Step 3: Smoke-run**

Run: `npm run dev` + `npm run dev:app`
Expected: a frameless transparent window in the bottom-right; clicks pass through to whatever is behind it; it stays above other windows; no taskbar entry.

- [ ] **Step 4: Commit**

```bash
git add overlay/main.js
git commit -m "feat(overlay): transparent frameless always-on-top click-through window

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: three.js transparent renderer (smoke object)

**Files:**
- Modify: `overlay/renderer/main.js`

**Interfaces:**
- Produces: a transparent-background WebGL scene with a rotating cube (proves the render pipeline before VRM).

- [ ] **Step 1: Replace `overlay/renderer/main.js`**

```javascript
import * as THREE from "three";

const app = document.getElementById("app");
const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
renderer.setClearColor(0x000000, 0); // fully transparent
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

const cube = new THREE.Mesh(
  new THREE.BoxGeometry(0.4, 0.4, 0.4),
  new THREE.MeshStandardMaterial({ color: 0x66ccff })
);
cube.position.set(0, 1.2, 0);
scene.add(cube);

const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = clock.getDelta();
  cube.rotation.y += dt;
  renderer.render(scene, camera);
}
animate();

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
```

- [ ] **Step 2: Smoke-run** — `npm run dev` + `npm run dev:app`. Expected: a rotating cube floats on the transparent desktop.

- [ ] **Step 3: Commit**

```bash
git add overlay/renderer/main.js
git commit -m "feat(overlay): transparent three.js scene with smoke cube

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Load and display a sample VRM

**Files:**
- Create: `overlay/renderer/vrm.js`
- Modify: `overlay/renderer/main.js`

**Interfaces:**
- Produces: `async loadVRM(scene, url) -> vrm` (loads a `.vrm`, adds `vrm.scene` to the scene, applies VRM0 rotation, returns the `vrm`). Throws a clear error if the file is missing.

- [ ] **Step 1: Create `overlay/renderer/vrm.js`**

```javascript
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils } from "@pixiv/three-vrm";

export async function loadVRM(scene, url) {
  const loader = new GLTFLoader();
  loader.register((parser) => new VRMLoaderPlugin(parser));
  let gltf;
  try {
    gltf = await loader.loadAsync(url);
  } catch (e) {
    throw new Error(`VRM の読み込みに失敗しました: ${url} (${e.message})`);
  }
  const vrm = gltf.userData.vrm;
  if (!vrm) throw new Error(`VRM データが見つかりません: ${url}`);
  VRMUtils.rotateVRM0(vrm); // face +Z for VRM0 models (no-op for VRM1)
  scene.add(vrm.scene);
  return vrm;
}
```

- [ ] **Step 2: Modify `overlay/renderer/main.js`** — remove the cube block (the `const cube = ...` and `scene.add(cube)` and `cube.rotation.y += dt`) and load the VRM instead. After the lights, add:
```javascript
import { loadVRM } from "./vrm.js";

let vrm = null;
loadVRM(scene, "../assets/sample.vrm")
  .then((v) => { vrm = v; })
  .catch((err) => console.error(err.message));
```
And in `animate()` replace `cube.rotation.y += dt;` with:
```javascript
  if (vrm) vrm.update(dt);
```

- [ ] **Step 3: Provide a sample VRM** — place a permissively-licensed sample at `overlay/assets/sample.vrm` (e.g. a VRoid sample export). Document this in `overlay/README` notes; if absent, the console shows the clear error from Step 1.

- [ ] **Step 4: Smoke-run** — Expected: the VRM character renders on the transparent desktop (static pose).

- [ ] **Step 5: Commit**

```bash
git add overlay/renderer/vrm.js overlay/renderer/main.js
git commit -m "feat(overlay): load and render a sample VRM

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Idle motion (blink + sway)

**Files:**
- Modify: `overlay/renderer/vrm.js`, `overlay/renderer/main.js`

**Interfaces:**
- Produces: `updateIdle(vrm, elapsed, dt)` — applies periodic blink (via `expressionManager`) and a subtle upper-body sway; calls `vrm.update(dt)` last.

- [ ] **Step 1: Add to `overlay/renderer/vrm.js`**

```javascript
import { VRMHumanBoneName } from "@pixiv/three-vrm";

export function updateIdle(vrm, elapsed, dt) {
  // subtle sway on the spine
  const spine = vrm.humanoid?.getNormalizedBoneNode(VRMHumanBoneName.Spine);
  if (spine) spine.rotation.y = Math.sin(elapsed * 0.8) * 0.03;

  // periodic blink: a quick close every ~4s
  const em = vrm.expressionManager;
  if (em) {
    const phase = elapsed % 4.0;
    const blink = phase < 0.12 ? 1.0 - Math.abs(phase - 0.06) / 0.06 : 0.0;
    em.setValue("blink", Math.max(0, Math.min(1, blink)));
  }
  vrm.update(dt);
}
```

- [ ] **Step 2: Modify `overlay/renderer/main.js`** — replace `if (vrm) vrm.update(dt);` in `animate()` with:
```javascript
  if (vrm) updateIdle(vrm, clock.elapsedTime, dt);
```
and add `import { loadVRM, updateIdle } from "./vrm.js";` (merge with the existing import).

- [ ] **Step 3: Smoke-run** — Expected: the character blinks periodically and sways gently.

- [ ] **Step 4: Commit**

```bash
git add overlay/renderer/vrm.js overlay/renderer/main.js
git commit -m "feat(overlay): idle blink and sway

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: Config loader (pure, unit-tested)

**Files:**
- Create: `overlay/renderer/config.js`, `overlay/config.json`, `overlay/test/config.test.js`

**Interfaces:**
- Produces: `mergeConfig(userConfig) -> config` merging over defaults `{ vrmUrl, wsUrl, width, height, fps }`. Pure (no I/O), so it is unit-testable.

- [ ] **Step 1: Write the failing test `overlay/test/config.test.js`**

```javascript
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
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd overlay && npx vitest run test/config.test.js`
Expected: FAIL (cannot import `mergeConfig` / `config.js` missing).

- [ ] **Step 3: Create `overlay/renderer/config.js`**

```javascript
export const DEFAULTS = {
  vrmUrl: "../assets/sample.vrm",
  wsUrl: "ws://127.0.0.1:8770/ws",
  width: 400,
  height: 600,
  fps: 30,
};

export function mergeConfig(userConfig) {
  const out = { ...DEFAULTS };
  for (const [k, v] of Object.entries(userConfig || {})) {
    if (v !== undefined && k in DEFAULTS) out[k] = v;
  }
  return out;
}
```

- [ ] **Step 4: Create `overlay/config.json`**

```json
{
  "vrmUrl": "../assets/sample.vrm",
  "wsUrl": "ws://127.0.0.1:8770/ws",
  "width": 400,
  "height": 600,
  "fps": 30
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `npx vitest run test/config.test.js`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add overlay/renderer/config.js overlay/config.json overlay/test/config.test.js
git commit -m "feat(overlay): config loader with defaults merge

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: State/amplitude mappings (pure, unit-tested)

**Files:**
- Create: `overlay/renderer/mappings.js`, `overlay/test/mappings.test.js`

**Interfaces:**
- Produces: `amplitudeToMouth(level) -> number` (clamp 0..1) and `isValidState(value) -> boolean` for the four states.

- [ ] **Step 1: Write the failing test `overlay/test/mappings.test.js`**

```javascript
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run test/mappings.test.js`
Expected: FAIL (module missing).

- [ ] **Step 3: Create `overlay/renderer/mappings.js`**

```javascript
export const STATES = ["idle", "listening", "thinking", "speaking"];

export function isValidState(value) {
  return STATES.includes(value);
}

export function amplitudeToMouth(level) {
  if (!Number.isFinite(level)) return 0;
  return Math.max(0, Math.min(1, level));
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run test/mappings.test.js`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add overlay/renderer/mappings.js overlay/test/mappings.test.js
git commit -m "feat(overlay): state/amplitude mapping helpers

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: WebSocket client (parse + backoff unit-tested; live connect manual)

**Files:**
- Create: `overlay/renderer/ws-client.js`, `overlay/test/ws-client.test.js`
- Modify: `overlay/renderer/main.js`

**Interfaces:**
- Produces:
  - `parseMessage(data) -> {type, value} | null` (JSON-parses a WS frame; returns null on malformed or unknown type; validates `state` against the four states and coerces `mouth` to a clamped number).
  - `nextBackoff(attempt) -> ms` (exponential backoff capped, e.g. `min(1000 * 2**attempt, 10000)`).
  - `connect(wsUrl, handlers)` (opens a WS, wires onmessage→parse→handlers.onState/onMouth, retries on close with `nextBackoff`). Live socket behavior is verified manually.

- [ ] **Step 1: Write the failing test `overlay/test/ws-client.test.js`**

```javascript
import { describe, it, expect } from "vitest";
import { parseMessage, nextBackoff } from "../renderer/ws-client.js";

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
});

describe("nextBackoff", () => {
  it("grows exponentially and caps at 10s", () => {
    expect(nextBackoff(0)).toBe(1000);
    expect(nextBackoff(1)).toBe(2000);
    expect(nextBackoff(20)).toBe(10000);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `npx vitest run test/ws-client.test.js`
Expected: FAIL (module missing).

- [ ] **Step 3: Create `overlay/renderer/ws-client.js`**

```javascript
import { isValidState, amplitudeToMouth } from "./mappings.js";

export function parseMessage(data) {
  let obj;
  try {
    obj = JSON.parse(data);
  } catch {
    return null;
  }
  if (!obj || typeof obj !== "object") return null;
  if (obj.type === "state") {
    return isValidState(obj.value) ? { type: "state", value: obj.value } : null;
  }
  if (obj.type === "mouth") {
    return { type: "mouth", value: amplitudeToMouth(Number(obj.value)) };
  }
  return null;
}

export function nextBackoff(attempt) {
  return Math.min(1000 * 2 ** attempt, 10000);
}

// Live connect with auto-reconnect. handlers: { onState(value), onMouth(level) }.
export function connect(wsUrl, handlers) {
  let attempt = 0;
  let ws = null;
  let stopped = false;

  function open() {
    if (stopped) return;
    ws = new WebSocket(wsUrl);
    ws.onopen = () => { attempt = 0; };
    ws.onmessage = (ev) => {
      const msg = parseMessage(ev.data);
      if (!msg) return;
      if (msg.type === "state") handlers.onState?.(msg.value);
      else if (msg.type === "mouth") handlers.onMouth?.(msg.value);
    };
    ws.onclose = () => {
      handlers.onState?.("idle"); // fall back to idle while disconnected
      if (!stopped) setTimeout(open, nextBackoff(attempt++));
    };
    ws.onerror = () => { try { ws.close(); } catch {} };
  }
  open();
  return () => { stopped = true; try { ws?.close(); } catch {} };
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `npx vitest run test/ws-client.test.js`
Expected: PASS (6 tests).

- [ ] **Step 5: Wire into `overlay/renderer/main.js`** — add near the top (after VRM load):
```javascript
import { connect } from "./ws-client.js";
import { mergeConfig } from "./config.js";

const cfg = mergeConfig({}); // SP1: defaults; config.json wiring can come later
let currentState = "idle";
let mouthTarget = 0;
connect(cfg.wsUrl, {
  onState: (v) => { currentState = v; },
  onMouth: (level) => { mouthTarget = level; },
});
```
and in `animate()`, after `updateIdle(...)`, drive the mouth when speaking:
```javascript
  if (vrm?.expressionManager) {
    const open = currentState === "speaking" ? mouthTarget : 0;
    vrm.expressionManager.setValue("aa", open);
    vrm.expressionManager.update();
  }
```

- [ ] **Step 6: Commit**

```bash
git add overlay/renderer/ws-client.js overlay/test/ws-client.test.js overlay/renderer/main.js
git commit -m "feat(overlay): websocket client with parse + backoff and lip-sync wiring

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: Mock injector for standalone verification

**Files:**
- Create: `overlay/renderer/mock-injector.js`
- Modify: `overlay/renderer/main.js`

**Interfaces:**
- Produces: `installMockInjector({ onState, onMouth })` — keyboard shortcuts to drive states/mouth without Python (1=idle, 2=listening, 3=thinking, 4=speaking; while `4` held / `m` pressed, oscillate mouth). For standalone verification only.

- [ ] **Step 1: Create `overlay/renderer/mock-injector.js`**

```javascript
// Standalone verification: drive state/mouth from the keyboard (no Python needed).
export function installMockInjector({ onState, onMouth }) {
  const map = { "1": "idle", "2": "listening", "3": "thinking", "4": "speaking" };
  let osc = null;
  window.addEventListener("keydown", (e) => {
    if (map[e.key]) {
      onState?.(map[e.key]);
      if (e.key === "4" && !osc) {
        let t = 0;
        osc = setInterval(() => { t += 0.1; onMouth?.((Math.sin(t * 8) + 1) / 2); }, 33);
      }
      if (e.key !== "4" && osc) { clearInterval(osc); osc = null; onMouth?.(0); }
    }
  });
}
```

- [ ] **Step 2: Wire into `overlay/renderer/main.js`** (only when not connected to Python — for SP1 always install it; it is harmless alongside WS):
```javascript
import { installMockInjector } from "./mock-injector.js";
installMockInjector({
  onState: (v) => { currentState = v; },
  onMouth: (level) => { mouthTarget = level; },
});
```

- [ ] **Step 3: Smoke-run** — `npm run dev` + `npm run dev:app`. Press `4`: the mouth oscillates (speaking); press `1`: mouth closes (idle). Verifies the full state/mouth → VRM path without Python.

- [ ] **Step 4: Commit**

```bash
git add overlay/renderer/mock-injector.js overlay/renderer/main.js
git commit -m "feat(overlay): keyboard mock injector for standalone verification

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Completion check (SP1 smoke)

- [ ] `cd overlay && npx vitest run` — all pure-logic unit tests pass (config, mappings, ws-client).
- [ ] `npm run dev` + `npm run dev:app` — a transparent, frameless, always-on-top, click-through window shows the sample VRM idling (blink + sway); the keyboard mock injector drives state/mouth (mouth moves on `4`/speaking).
- [ ] With SP2 running (`Config(overlay_enabled=True)` + `python -m kotoha.local_app`), the overlay reflects real `state`/`mouth` over `ws://127.0.0.1:8770/ws`.

## Acceptance (spec §10, SP1)

- A sample VRM renders in a transparent, always-on-top, click-through window that does not block desktop interaction, runnable standalone (no Python). The overlay consumes the SP2 WS protocol and animates state + lip-sync; on disconnect it falls back to idle and reconnects with backoff.
