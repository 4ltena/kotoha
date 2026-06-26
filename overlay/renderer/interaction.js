import { throwVelocity } from "./physics.js";

// Wires window pointer events to drag/hover callbacks. The window forwards
// pointer move even while click-through (setIgnoreMouseEvents forward:true),
// so hover detection works when not interactive. Pointer capture keeps the
// drag alive when the cursor leaves the small window.
export function installInteraction(cb) {
  let over = false;
  let dragging = false;
  let last = null;
  let samples = [];

  window.addEventListener("pointermove", (e) => {
    if (!dragging) {
      const nowOver = cb.isOverCharacter(e.clientX, e.clientY);
      if (nowOver !== over) {
        over = nowOver;
        cb.onHover(over);
      }
      return;
    }
    const dx = e.screenX - last.x;
    const dy = e.screenY - last.y;
    last = { x: e.screenX, y: e.screenY };
    samples.push({ x: e.screenX, y: e.screenY, t: performance.now() });
    if (samples.length > 6) samples.shift();
    cb.onDragMove(dx, dy);
  });

  window.addEventListener("pointerdown", (e) => {
    if (!cb.isOverCharacter(e.clientX, e.clientY)) return;
    dragging = true;
    last = { x: e.screenX, y: e.screenY };
    samples = [{ x: e.screenX, y: e.screenY, t: performance.now() }];
    try { e.target.setPointerCapture(e.pointerId); } catch {}
    cb.onDragStart();
  });

  window.addEventListener("pointerup", (e) => {
    if (!dragging) return;
    dragging = false;
    try { e.target.releasePointerCapture(e.pointerId); } catch {}
    cb.onDragEnd(throwVelocity(samples));
    samples = [];
  });
}
