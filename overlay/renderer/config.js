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
    if (v != null && k in DEFAULTS) out[k] = v;
  }
  return out;
}
