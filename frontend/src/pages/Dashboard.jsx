import { useCallback, useMemo } from "react";
import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardActionArea from "@mui/material/CardActionArea";
import CardContent from "@mui/material/CardContent";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid2";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import DoorFrontIcon from "@mui/icons-material/DoorFront";
import ReportProblemIcon from "@mui/icons-material/ReportProblem";
import SensorsIcon from "@mui/icons-material/Sensors";
import TimerIcon from "@mui/icons-material/Timer";
import AddIcon from "@mui/icons-material/Add";
import RefreshIcon from "@mui/icons-material/Refresh";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import CropFreeIcon from "@mui/icons-material/CropFree";

import { analytics, cameras as camerasApi, events as eventsApi, monitoring } from "../api/endpoints";
import { usePolling } from "../hooks/usePolling";
import { useMonitoringActions } from "../hooks/useMonitoringActions";
import { Loading, EmptyState, ErrorState } from "../components/DataStates";
import PageHeader from "../components/PageHeader";
import StatCard from "../components/StatCard";
import { RoleGate } from "../components/ProtectedRoute";
import LiveView from "../components/LiveView";
import { RiskChip, StateChip, WorkerChip } from "../components/StatusChips";
import { POLL_INTERVAL_MS } from "../utils/constants";
import { formatDuration, formatPct, summarizeObjects } from "../utils/format";

/** Colour the accessibility bar by state, not by value — the thresholds are
 *  per-camera on the backend, so the state it decided is the truth. */
const BAR_COLOR = { CLEAR: "success", PARTIAL: "warning", FULL: "error", UNKNOWN: "inherit" };

const SEVERITY = { FULL: 3, PARTIAL: 2, UNKNOWN: 1, CLEAR: 0 };

function IdleCard({ camera, onStart, busy }) {
  const needsZone = camera.strategy === "zone_based" && !camera.door_polygon?.length;
  return (
    <Card sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <Box
        sx={{
          height: 190,
          display: "grid",
          placeItems: "center",
          bgcolor: "#05070d",
          color: "grey.600",
        }}
      >
        <Typography variant="body2">Not monitored</Typography>
      </Box>
      <CardContent sx={{ flexGrow: 1 }}>
        <Typography variant="subtitle1" noWrap sx={{ fontWeight: 700 }}>
          {camera.name}
        </Typography>
        <Typography variant="caption" color="text.secondary" noWrap display="block">
          {camera.location || "No location set"}
        </Typography>

        <Stack direction="row" spacing={1} sx={{ mt: 2 }} flexWrap="wrap" useFlexGap>
          {needsZone ? (
            // Zone-based measures obstruction against a drawn polygon; without
            // one there is nothing to measure, so send the operator there first.
            <Button
              size="small"
              variant="contained"
              color="warning"
              startIcon={<CropFreeIcon />}
              component={RouterLink}
              to={`/cameras/${camera.id}/zone`}
            >
              Draw exit region
            </Button>
          ) : (
            <Button
              size="small"
              variant="contained"
              startIcon={<PlayArrowIcon />}
              disabled={busy}
              onClick={() => onStart(camera.id)}
            >
              Start monitoring
            </Button>
          )}
          <Button size="small" component={RouterLink} to={`/cameras/${camera.id}`} color="inherit">
            Details
          </Button>
        </Stack>
      </CardContent>
    </Card>
  );
}

function ExitCard({ status }) {
  const accessibility = Number(status.accessibility_pct ?? 0);
  return (
    <Card sx={{ height: "100%", display: "flex", flexDirection: "column" }}>
      <LiveView cameraId={status.camera_id} height={190} />
      <CardActionArea component={RouterLink} to={`/cameras/${status.camera_id}`}>
        <CardContent>
          <Stack
            direction="row"
            justifyContent="space-between"
            alignItems="flex-start"
            spacing={1}
          >
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" noWrap sx={{ fontWeight: 700 }}>
                {status.camera_name}
              </Typography>
              <Typography variant="caption" color="text.secondary" noWrap display="block">
                {status.location || "No location set"}
              </Typography>
            </Box>
            <StateChip state={status.state} />
          </Stack>

          <Box sx={{ mt: 2 }}>
            <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
              <Typography variant="caption" color="text.secondary">
                Accessible
              </Typography>
              <Typography variant="caption" sx={{ fontWeight: 700 }}>
                {formatPct(accessibility)}
              </Typography>
            </Stack>
            <LinearProgress
              variant="determinate"
              value={Math.max(0, Math.min(100, accessibility))}
              color={BAR_COLOR[status.state] || "inherit"}
              sx={{ height: 8, borderRadius: 4 }}
            />
          </Box>

          <Divider sx={{ my: 1.5 }} />

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
            <WorkerChip state={status.worker_state} />
            <RiskChip level={status.risk_level} score={status.risk_score} />
            {status.blocked && (
              <Tooltip title="How long this blockage has been confirmed">
                <Typography variant="caption" color="text.secondary">
                  {formatDuration(status.blocked_duration_s)}
                </Typography>
              </Tooltip>
            )}
          </Stack>

          {status.blocking_objects?.length > 0 && (
            <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
              Blocked by {summarizeObjects(status.blocking_objects, 3)}
            </Typography>
          )}
          {status.error && (
            <Typography variant="caption" color="error.main" sx={{ mt: 1, display: "block" }}>
              {status.error}
            </Typography>
          )}
        </CardContent>
      </CardActionArea>
    </Card>
  );
}

export default function Dashboard() {
  const {
    data: statuses,
    error,
    loading,
    refresh,
  } = usePolling(({ signal }) => monitoring.statusAll({ signal }), {
    intervalMs: POLL_INTERVAL_MS,
  });

  // /monitoring/status only reports cameras that have a *worker*, so a
  // registered-but-stopped exit would silently disappear from the wall
  // display. The camera list is what makes those visible and startable.
  const { data: cameraList, refresh: refreshCameras } = usePolling(
    ({ signal }) => camerasApi.list(undefined, { signal }),
    { intervalMs: 30000 }
  );

  const { data: summary } = usePolling(({ signal }) => analytics.summary(7, { signal }), {
    intervalMs: 30000,
  });
  const { data: overview } = usePolling(({ signal }) => eventsApi.overview({ signal }), {
    intervalMs: 15000,
  });

  const refreshAll = useCallback(async () => {
    await Promise.all([refresh(), refreshCameras()]);
  }, [refresh, refreshCameras]);

  const { busyId, start } = useMonitoringActions(refreshAll);

  // Worst first: on a wall display the top-left card must be the exit that
  // needs someone walking to it. Idle cameras sort last — they are a
  // configuration task, not an incident.
  const monitored = useMemo(
    () =>
      [...(statuses || [])].sort(
        (a, b) =>
          (SEVERITY[b.state] ?? 0) - (SEVERITY[a.state] ?? 0) ||
          (b.risk_score ?? 0) - (a.risk_score ?? 0) ||
          a.camera_name.localeCompare(b.camera_name)
      ),
    [statuses]
  );

  const idle = useMemo(() => {
    const monitoredIds = new Set((statuses || []).map((s) => s.camera_id));
    return (cameraList || []).filter((camera) => !monitoredIds.has(camera.id));
  }, [cameraList, statuses]);

  const blockedNow = monitored.filter((s) => s.blocked).length;
  const nothingRegistered = !loading && monitored.length === 0 && idle.length === 0;

  return (
    <Box>
      <PageHeader
        title="Live exits"
        subtitle="Every monitored exit, worst first. Updates every few seconds."
        actions={
          <>
            <Button startIcon={<RefreshIcon />} onClick={refreshAll} color="inherit">
              Refresh
            </Button>
            <RoleGate minimum="member">
              <Button
                startIcon={<AddIcon />}
                variant="contained"
                component={RouterLink}
                to="/cameras/new"
              >
                Add exit
              </Button>
            </RoleGate>
          </>
        }
      />

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label="Monitored"
            value={summary?.cameras_monitored ?? monitored.length}
            hint={`${summary?.cameras_total ?? monitored.length + idle.length} registered`}
            icon={<SensorsIcon />}
            color="info"
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label="Blocked now"
            value={blockedNow}
            hint={blockedNow ? "Needs attention" : "All exits accessible"}
            icon={<ReportProblemIcon />}
            color={blockedNow ? "error" : "success"}
          />
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <CardActionArea
            component={RouterLink}
            to="/events?status=detected"
            sx={{ borderRadius: 1, height: "100%" }}
          >
            <StatCard
              label="Unacknowledged"
              value={overview?.unacknowledged_events ?? "—"}
              hint={
                overview
                  ? `${overview.open_events} unresolved · ${overview.events_24h} in 24h`
                  : ""
              }
              icon={<DoorFrontIcon />}
              color={overview?.high_risk_open_events ? "error" : "warning"}
            />
          </CardActionArea>
        </Grid>
        <Grid size={{ xs: 6, md: 3 }}>
          <StatCard
            label="Avg blockage"
            value={summary ? formatDuration(summary.avg_duration_s) : "—"}
            hint={summary ? `longest ${formatDuration(summary.max_duration_s)}` : ""}
            icon={<TimerIcon />}
            color="secondary"
          />
        </Grid>
      </Grid>

      <ErrorState error={error} onRetry={refreshAll} title="Could not load live status" />

      {loading && !statuses ? (
        <Loading label="Contacting the detection service…" height={280} />
      ) : nothingRegistered ? (
        <EmptyState
          title="No exits are registered"
          description="Register a camera and start monitoring it. An RTSP URL works, and so does a path to a local video file if you want to exercise the pipeline without hardware."
          action={
            <Button
              variant="contained"
              component={RouterLink}
              to="/cameras/new"
              startIcon={<AddIcon />}
            >
              Add your first exit
            </Button>
          }
        />
      ) : (
        <Grid container spacing={2}>
          {monitored.map((status) => (
            <Grid key={`live-${status.camera_id}`} size={{ xs: 12, sm: 6, lg: 4 }}>
              <ExitCard status={status} />
            </Grid>
          ))}
          {idle.map((camera) => (
            <Grid key={`idle-${camera.id}`} size={{ xs: 12, sm: 6, lg: 4 }}>
              <IdleCard camera={camera} onStart={start} busy={busyId === camera.id} />
            </Grid>
          ))}
        </Grid>
      )}
    </Box>
  );
}
