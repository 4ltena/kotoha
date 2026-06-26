import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { VRMLoaderPlugin, VRMUtils, VRMHumanBoneName } from "@pixiv/three-vrm";

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

export function updateIdle(vrm, elapsed) {
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
}
