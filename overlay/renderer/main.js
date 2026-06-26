import * as THREE from "three";
import { loadVRM, updateIdle } from "./vrm.js";
import { connect } from "./ws-client.js";
import { mergeConfig } from "./config.js";
import { installMockInjector } from "./mock-injector.js";

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

let vrm = null;
let placeholder = null;
loadVRM(scene, "../assets/sample.vrm")
  .then((v) => { vrm = v; })
  .catch((err) => {
    // 仮 VRM 未配置でも起動を目視確認できるよう、簡易プレースホルダを表示する
    console.error(err.message);
    placeholder = new THREE.Mesh(
      new THREE.BoxGeometry(0.4, 0.4, 0.4),
      new THREE.MeshStandardMaterial({ color: 0x66ccff })
    );
    placeholder.position.set(0, 1.2, 0);
    scene.add(placeholder);
  });

const cfg = mergeConfig({}); // SP1: defaults; config.json wiring can come later
let currentState = "idle";
let mouthTarget = 0;
connect(cfg.wsUrl, {
  onState: (v) => { currentState = v; },
  onMouth: (level) => { mouthTarget = level; },
});

installMockInjector({
  onState: (v) => { currentState = v; },
  onMouth: (level) => { mouthTarget = level; },
});

const clock = new THREE.Clock();
function animate() {
  requestAnimationFrame(animate);
  const dt = clock.getDelta();
  if (vrm) updateIdle(vrm, clock.elapsedTime);
  if (vrm?.expressionManager) {
    const open = currentState === "speaking" ? mouthTarget : 0;
    vrm.expressionManager.setValue("aa", open);
  }
  if (vrm) vrm.update(dt);
  if (placeholder) placeholder.rotation.y += dt;
  renderer.render(scene, camera);
}
animate();

window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});
