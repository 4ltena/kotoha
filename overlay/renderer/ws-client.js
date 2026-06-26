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
    if (typeof obj.value !== "number") return null;
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
