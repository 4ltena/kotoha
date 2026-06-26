export const STATES = ["idle", "listening", "thinking", "speaking"];

export function isValidState(value) {
  return STATES.includes(value);
}

export function amplitudeToMouth(level) {
  if (!Number.isFinite(level)) return 0;
  return Math.max(0, Math.min(1, level));
}
