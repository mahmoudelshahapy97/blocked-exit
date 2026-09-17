import dayjs from "dayjs";
import relativeTime from "dayjs/plugin/relativeTime";
import utc from "dayjs/plugin/utc";

dayjs.extend(relativeTime);
dayjs.extend(utc);

/** Backend timestamps are timezone-aware ISO strings; render them locally. */
export const formatDateTime = (value) =>
  value ? dayjs(value).format("YYYY-MM-DD HH:mm:ss") : "—";

export const formatDate = (value) => (value ? dayjs(value).format("YYYY-MM-DD") : "—");

export const fromNow = (value) => (value ? dayjs(value).fromNow() : "—");

/** Seconds as a human span: 45s, 3m 20s, 2h 05m. */
export function formatDuration(seconds) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "—";
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  const minutes = Math.floor(total / 60);
  const secs = total % 60;
  if (minutes < 60) return `${minutes}m ${String(secs).padStart(2, "0")}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${String(minutes % 60).padStart(2, "0")}m`;
}

export const formatPct = (value, digits = 1) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : `${Number(value).toFixed(digits)}%`;

export const formatNumber = (value, digits = 0) =>
  value === null || value === undefined || Number.isNaN(value)
    ? "—"
    : Number(value).toLocaleString(undefined, {
        minimumFractionDigits: digits,
        maximumFractionDigits: digits,
      });

/**
 * RTSP URLs routinely carry credentials, and this console is shown on wall
 * displays. Mirrors app/core/redaction.py so the browser never renders a
 * password the backend takes care to strip from its own logs.
 */
export function redactUrl(url) {
  if (!url) return "—";
  try {
    const parsed = new URL(url);
    if (parsed.password) parsed.password = "***";
    return parsed.toString();
  } catch {
    // Local video file paths are not URLs at all — show them as they are.
    return url.replace(/\/\/([^:/@]+):([^@]+)@/, "//$1:***@");
  }
}

/** "chair, backpack +2" — the at-a-glance summary of what is in the way. */
export function summarizeObjects(objects, max = 2) {
  if (!objects?.length) return "—";
  const labels = objects.map((o) => o.label);
  const shown = labels.slice(0, max).join(", ");
  const rest = labels.length - max;
  return rest > 0 ? `${shown} +${rest}` : shown;
}
