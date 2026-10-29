/**
 * Back-screen robot data contract, version 1.
 *
 * The robot may supply data either through window.ROBOT_DATA_ADAPTER or the
 * HTTP endpoints documented in docs/ROBOT_API_CONTRACT.md. This module keeps
 * partial or newly introduced fields from breaking the screen.
 */
export const ROBOT_API_VERSION = 'v1';

export function normalizeSnapshot(raw) {
  const data = raw && typeof raw === 'object' ? (raw.data || raw) : {};
  return {
    ...data,
    health: { level: 'normal', alertCount: 0, ...(data.health || {}) },
    motion: { ...(data.motion || {}) },
    battery: { ...(data.battery || {}) },
    battery2: { ...(data.battery2 || {}) },
    sensors: { ...(data.sensors || {}) },
    network: { ...(data.network || {}) },
  };
}

export function normalizeWorkSummary(raw) {
  const data = raw && typeof raw === 'object' ? (raw.data || raw) : {};
  return { ...data, tasks: Array.isArray(data.tasks) ? data.tasks : [] };
}

export function isRobotInterfaceConfigured() {
  return Boolean(window.ROBOT_DATA_ADAPTER || window.ROBOT_DIAGNOSTIC_API);
}
