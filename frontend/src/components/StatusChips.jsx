import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import { RISK_COLOR, STATE_COLOR, STRATEGY_LABEL, WORKER_COLOR } from "../utils/constants";

const STATE_HINT = {
  CLEAR: "The exit is accessible",
  PARTIAL: "The exit is partly obstructed",
  FULL: "The exit is effectively impassable",
  UNKNOWN: "No verdict yet — the worker has not produced a frame",
};

export function StateChip({ state, size = "small", ...props }) {
  const value = state || "UNKNOWN";
  return (
    <Tooltip title={STATE_HINT[value] || ""}>
      <Chip
        label={value}
        color={STATE_COLOR[value] || "default"}
        size={size}
        variant={value === "UNKNOWN" ? "outlined" : "filled"}
        {...props}
      />
    </Tooltip>
  );
}

export function RiskChip({ level, score, size = "small", ...props }) {
  const value = level || "LOW";
  return (
    <Chip
      label={score === undefined ? value : `${value} · ${Number(score).toFixed(0)}`}
      color={RISK_COLOR[value] || "default"}
      size={size}
      // CRITICAL and HIGH share a palette entry; the outline keeps them apart
      // at a glance on a wall display.
      variant={value === "CRITICAL" ? "filled" : "outlined"}
      {...props}
    />
  );
}

export function WorkerChip({ state, size = "small", ...props }) {
  const value = state || "stopped";
  return (
    <Chip
      label={value}
      color={WORKER_COLOR[value] || "default"}
      size={size}
      variant="outlined"
      {...props}
    />
  );
}

export function StrategyChip({ strategy, size = "small", ...props }) {
  return (
    <Chip
      label={STRATEGY_LABEL[strategy] || strategy || "—"}
      size={size}
      variant="outlined"
      {...props}
    />
  );
}
