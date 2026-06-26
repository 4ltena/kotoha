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
    disp = { workArea: { x: 0, y: 0, width: screen.availWidth, height: screen.availHeight }, bounds: { x: 0, y: 0 } };
  }
  const wa = disp.workArea;
  bounds.minX = wa.x;
  bounds.maxX = wa.x + wa.width - WIN_W;
  bounds.floorY = wa.y + wa.height - WIN_H;
  pos.x = disp.bounds ? disp.bounds.x : bounds.maxX;
  pos.y = bounds.floorY;
}
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
      pos.y = Math.max(0, Math.min(bounds.floorY, pos.y + dy));
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
    if (pos.grounded) {
      if (currentState !== "speaking") {
        const w = walker.update(walkState, pos.x, dt, bounds, Math.random);
        walkState = w.state;
        facing = w.facing;
        pos.x = Math.max(bounds.minX, Math.min(bounds.maxX, pos.x + w.dx));
      }
      pos.vx = 0; // on ground the walker owns x; drop leftover throw velocity
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
    if (vrm.scene) vrm.scene.scale.x = facing >= 0 ? 1 : -1;
    if (vrm.expressionManager) {
      const open = currentState === "speaking" ? mouthTarget : 0;
      vrm.expressionManager.setValue("aa", open);
    }
    vrm.update(dt);
  }
  if (placeholder) placeholder.rotation.y += dt;
  renderer.render(scene, camera);
}
initBounds().then(() => animate());

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
