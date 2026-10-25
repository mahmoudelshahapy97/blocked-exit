/** Mirrors app/core/enums.py — keep the two in step. */

export const BLOCKAGE_STATE = {
  CLEAR: "CLEAR",
  PARTIAL: "PARTIAL",
  FULL: "FULL",
  UNKNOWN: "UNKNOWN",
};

export const RISK_LEVEL = {
  LOW: "LOW",
  MEDIUM: "MEDIUM",
  HIGH: "HIGH",
  CRITICAL: "CRITICAL",
};

/** The operator workflow: detected -> acknowledged -> resolved. */
export const EVENT_STATUS = {
  DETECTED: "detected",
  ACKNOWLEDGED: "acknowledged",
  RESOLVED: "resolved",
};

export const EVENT_STATUS_COLOR = {
  detected: "error",
  acknowledged: "warning",
  resolved: "success",
};

export const STRATEGY = {
  ZONE_BASED: "zone_based",
  DOOR_CENTRIC: "door_centric",
};

export const STRATEGY_LABEL = {
  zone_based: "Zone based",
  door_centric: "Door centric",
};

export const WORKER_STATE = {
  STOPPED: "stopped",
  STARTING: "starting",
  RUNNING: "running",
  RECONNECTING: "reconnecting",
  ERROR: "error",
};

export const ALERT_CHANNEL = { WEBHOOK: "webhook", EMAIL: "email" };
export const ALERT_STATUS = {
  PENDING: "pending",
  SENT: "sent",
  FAILED: "failed",
  SKIPPED: "skipped",
};

/** MUI palette keys, so a state colours identically everywhere it appears. */
export const STATE_COLOR = {
  CLEAR: "success",
  PARTIAL: "warning",
  FULL: "error",
  UNKNOWN: "default",
};

export const RISK_COLOR = {
  LOW: "success",
  MEDIUM: "warning",
  HIGH: "error",
  CRITICAL: "error",
};

export const WORKER_COLOR = {
  running: "success",
  starting: "info",
  reconnecting: "warning",
  error: "error",
  stopped: "default",
};

export const POLL_INTERVAL_MS =
  Number(import.meta.env.VITE_POLL_INTERVAL_MS) || 3000;

/** The backend's password rule (app/schemas/auth.py), for form hints. */
export const PASSWORD_HELP =
  "At least 10 characters, with three of: lowercase, uppercase, digit, symbol.";
