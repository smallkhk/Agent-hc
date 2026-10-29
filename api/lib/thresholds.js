// Rule thresholds: env defaults and the bounds /handcam config accepts. No DB imports,
// so the command definitions can load without a full env.
const env = process.env;
const num = (value, fallback) => (value ? Number(value) : fallback);

// Bounds keep a typo from disabling a rule (e.g. VIOLATION_SEC=0).
export const THRESHOLDS = {
  graceSec: { min: 3, max: 120, default: num(env.GRACE_SEC, 10), int: true },
  violationSec: { min: 5, max: 600, default: num(env.VIOLATION_SEC, 30), int: true },
  freezeSec: { min: 3, max: 120, default: num(env.FREEZE_SEC, 8), int: true },
  dropSec: { min: 5, max: 600, default: num(env.DROP_SEC, 20), int: true },
  menuThreshold: { min: 0.5, max: 0.99, default: num(env.MENU_THRESHOLD, 0.8), int: false },
};
