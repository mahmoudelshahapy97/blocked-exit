import { useCallback, useEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import CircularProgress from "@mui/material/CircularProgress";
import IconButton from "@mui/material/IconButton";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import PauseIcon from "@mui/icons-material/Pause";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import OpenInNewIcon from "@mui/icons-material/OpenInNew";
import { monitoring } from "../api/endpoints";
import { POLL_INTERVAL_MS } from "../utils/constants";
import { useTranslation } from "react-i18next";

// Stream tickets are single-camera and expire after 60s (see
// POST /monitoring/{id}/stream-ticket) — refresh comfortably before that,
// or an embedded MJPEG view would go dark mid-shift.
const STREAM_TICKET_REFRESH_MS = 45_000;

/**
 * Annotated live view of one exit, in one of two modes:
 *
 *  - **snapshot** (default) — poll /snapshot as a blob and swap object URLs.
 *    Carries the Authorization header like any other API call, so it always
 *    works.
 *  - **stream** — the backend's MJPEG endpoint straight into an <img>. An
 *    <img> tag cannot send an Authorization header, so this fetches a
 *    short-lived, single-camera ticket first and puts that on the URL
 *    instead — re-fetched periodically so a long-open tab does not go dark
 *    when the ticket expires. Cheaper for the browser, but every refresh
 *    briefly reopens the MJPEG connection.
 *
 * Both cost the backend a JPEG encode per frame and MAX_MJPEG_CLIENTS caps the
 * streaming ones, so the view pauses itself whenever the tab is hidden.
 */
export function LiveView({
  cameraId,
  annotated = true,
  height = 300,
  mode = "snapshot",
  intervalMs = POLL_INTERVAL_MS,
  paused: pausedProp,
  onTogglePause,
}) {
  const { t } = useTranslation();
  const [internalPaused, setInternalPaused] = useState(false);
  const paused = pausedProp ?? internalPaused;
  const togglePause = onTogglePause || (() => setInternalPaused((p) => !p));

  const [src, setSrc] = useState(null);
  const [streamSrc, setStreamSrc] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);
  const objectUrlRef = useRef(null);

  const releaseObjectUrl = useCallback(() => {
    if (objectUrlRef.current) {
      URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;
    }
  }, []);

  // --- snapshot polling ---------------------------------------------------
  useEffect(() => {
    if (mode !== "snapshot" || paused) return undefined;

    let cancelled = false;
    let timer = null;
    let controller = null;

    const tick = async () => {
      if (cancelled) return;
      if (document.hidden) {
        timer = setTimeout(tick, intervalMs);
        return;
      }
      controller = new AbortController();
      try {
        const url = await monitoring.snapshot(cameraId, {
          annotated,
          signal: controller.signal,
        });
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        releaseObjectUrl();
        objectUrlRef.current = url;
        setSrc(url);
        setError(null);
      } catch (err) {
        if (!cancelled && err?.code !== "ERR_CANCELED") {
          // A worker that is not running answers 404/503 here; that is a
          // state to show, not a crash.
          setError(
            err?.response?.status === 404
              ? t("liveView.monitoringIsNotRunningFor")
              : t("liveView.noFrameAvailable")
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
      if (!cancelled) timer = setTimeout(tick, intervalMs);
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
      controller?.abort();
    };
  }, [cameraId, annotated, mode, paused, intervalMs, releaseObjectUrl, t]);

  // --- MJPEG stream ticket refresh -----------------------------------------
  useEffect(() => {
    if (mode !== "stream" || paused) return undefined;

    let cancelled = false;
    let timer = null;

    const tick = async () => {
      try {
        const url = await monitoring.streamUrl(cameraId);
        if (!cancelled) {
          setStreamSrc(url);
          setError(null);
        }
      } catch {
        if (!cancelled) {
          setError(t("liveView.couldNotStartTheLive"));
          setLoading(false);
        }
      }
      if (!cancelled) timer = setTimeout(tick, STREAM_TICKET_REFRESH_MS);
    };

    tick();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [cameraId, mode, paused, t]);

  // Revoking on unmount as well: without it every frame polled during the
  // component's life stays resident until the document is discarded.
  useEffect(() => releaseObjectUrl, [releaseObjectUrl]);

  const handleToggle = () => togglePause();

  const openStreamInNewTab = async () => {
    try {
      const url = await monitoring.streamUrl(cameraId);
      window.open(url, "_blank", "noopener,noreferrer");
    } catch {
      setError(t("liveView.couldNotStartTheLive"));
    }
  };

  return (
    <Box
      sx={{
        position: "relative",
        width: "100%",
        height,
        borderRadius: 2,
        overflow: "hidden",
        bgcolor: "#05070d",
        display: "grid",
        placeItems: "center",
      }}
    >
      {mode === "stream" ? (
        streamSrc && !paused ? (
          <Box
            component="img"
            src={streamSrc}
            alt={t("liveView.liveExitView")}
            onLoad={() => setLoading(false)}
            onError={() => {
              setLoading(false);
              setError(t("liveView.liveStreamUnavailableIsMonitoring"));
            }}
            sx={{ width: "100%", height: "100%", objectFit: "contain" }}
          />
        ) : null
      ) : src ? (
        <Box
          component="img"
          src={src}
          alt={t("liveView.latestAnnotatedFrame")}
          sx={{ width: "100%", height: "100%", objectFit: "contain" }}
        />
      ) : null}

      {loading && !error && (
        <Box sx={{ position: "absolute", display: "grid", placeItems: "center", gap: 1 }}>
          <CircularProgress size={26} />
        </Box>
      )}

      {error && (
        <Typography
          variant="body2"
          sx={{ position: "absolute", color: "grey.500", px: 3, textAlign: "center" }}
        >
          {error}
        </Typography>
      )}

      {paused && !loading && (
        <Chip
          label={t("liveView.paused")}
          size="small"
          sx={{ position: "absolute", bgcolor: "rgba(0,0,0,0.65)", color: "grey.100" }}
        />
      )}

      <Stack
        direction="row"
        spacing={0.5}
        sx={{
          position: "absolute",
          top: 8,
          right: 8,
          bgcolor: "rgba(5, 7, 13, 0.72)",
          borderRadius: 2,
          p: 0.25,
        }}
      >
        <Tooltip title={paused ? t("liveView.resume") : t("liveView.pause")}>
          <IconButton size="small" onClick={handleToggle} sx={{ color: "grey.300" }}>
            {paused ? <PlayArrowIcon fontSize="small" /> : <PauseIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
        <Tooltip title={t("liveView.openTheRawMjpegStream")}>
          <IconButton size="small" onClick={openStreamInNewTab} sx={{ color: "grey.300" }}>
            <OpenInNewIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </Stack>

      <Chip
        size="small"
        label={mode === "stream" ? t("liveView.mjpeg") : t("liveView.snapshotV0S", { v0: Math.round(intervalMs / 1000) })}
        sx={{
          position: "absolute",
          bottom: 8,
          left: 8,
          bgcolor: "rgba(5, 7, 13, 0.72)",
          color: "grey.300",
        }}
      />
    </Box>
  );
}

export default LiveView;
