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
