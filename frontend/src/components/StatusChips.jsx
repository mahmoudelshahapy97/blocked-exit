import Chip from "@mui/material/Chip";
import Tooltip from "@mui/material/Tooltip";
import {
  EVENT_STATUS_COLOR,
  RISK_COLOR,
  STATE_COLOR,
  STRATEGY_LABEL,
  WORKER_COLOR,
} from "../utils/constants";
import { useTranslation } from "react-i18next";
import i18n from "i18next";
import { titleCase } from "../utils/format";

const STATE_HINT = {
  get CLEAR() { return i18n.t("statusChips.theExitIsAccessible"); },
  get PARTIAL() { return i18n.t("statusChips.theExitIsPartlyObstructed"); },
  get FULL() { return i18n.t("statusChips.theExitIsEffectivelyImpassable"); },
  get UNKNOWN() { return i18n.t("statusChips.noVerdictYetTheWorker"); },
};

export function StateChip({ state, size = "small", ...props }) {
  useTranslation(); // re-render when the language changes
  const value = state || "UNKNOWN";
  return (
    <Tooltip title={STATE_HINT[value] || ""}>
      <Chip
        label={titleCase(value)}
        color={STATE_COLOR[value] || "default"}
        size={size}
        variant={value === "UNKNOWN" ? "outlined" : "filled"}
        {...props}
      />
    </Tooltip>
  );
}

export function RiskChip({ level, score, size = "small", ...props }) {
  useTranslation(); // re-render when the language changes
  const value = level || "LOW";
  return (
    <Chip
      label={score === undefined ? titleCase(value) : `${titleCase(value)} · ${Number(score).toFixed(0)}`}
      color={RISK_COLOR[value] || "default"}
      size={size}
      // CRITICAL and HIGH share a palette entry; the outline keeps them apart
      // at a glance on a wall display.
      variant={value === "CRITICAL" ? "filled" : "outlined"}
      {...props}
    />
  );
}

const EVENT_STATUS_HINT = {
  get detected() { return i18n.t("statusChips.nobodyHasAcknowledgedThisYet"); },
  get acknowledged() { return i18n.t("statusChips.someoneIsOnIt"); },
  get resolved() { return i18n.t("statusChips.closedByAnOperator"); },
};

export function EventStatusChip({ status, size = "small", ...props }) {
  useTranslation(); // re-render when the language changes
  const value = status || "detected";
  return (
    <Tooltip title={EVENT_STATUS_HINT[value] || ""}>
      <Chip
        label={titleCase(value)}
        color={EVENT_STATUS_COLOR[value] || "default"}
        size={size}
        variant={value === "detected" ? "filled" : "outlined"}
        {...props}
      />
    </Tooltip>
  );
}

export function WorkerChip({ state, size = "small", ...props }) {
  const value = state || "stopped";
  return (
    <Chip
      label={titleCase(value)}
      color={WORKER_COLOR[value] || "default"}
      size={size}
      variant="outlined"
      {...props}
    />
  );
}

export function StrategyChip({ strategy, size = "small", ...props }) {
  useTranslation(); // re-render when the language changes
  return (
    <Chip
      label={STRATEGY_LABEL[strategy] || strategy || "—"}
      size={size}
      variant="outlined"
      {...props}
    />
  );
}
