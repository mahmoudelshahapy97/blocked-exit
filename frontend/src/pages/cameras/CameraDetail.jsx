import { useCallback, useMemo, useState } from "react";
import { Link as RouterLink, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid2";
import LinearProgress from "@mui/material/LinearProgress";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import EditIcon from "@mui/icons-material/Edit";
import CropFreeIcon from "@mui/icons-material/CropFree";
import NotificationsActiveIcon from "@mui/icons-material/NotificationsActive";

import { errorMessage } from "../../api/client";
import { alerts as alertsApi, cameras as camerasApi, events as eventsApi, monitoring } from "../../api/endpoints";
import { usePolling } from "../../hooks/usePolling";
import { useAsync } from "../../hooks/useAsync";
import { useMonitoringActions } from "../../hooks/useMonitoringActions";
import { useToast } from "../../components/Toast";
import { EmptyState, ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import LiveView from "../../components/LiveView";
import { RiskChip, StateChip, StrategyChip, WorkerChip } from "../../components/StatusChips";
import { POLL_INTERVAL_MS } from "../../utils/constants";
import {
  formatDateTime,
  formatDuration,
  formatNumber,
  formatPct,
  fromNow,
  redactUrl,
} from "../../utils/format";

const BAR_COLOR = { CLEAR: "success", PARTIAL: "warning", FULL: "error", UNKNOWN: "inherit" };

function Field({ label, children }) {
  return (
    <Stack direction="row" justifyContent="space-between" spacing={2} sx={{ py: 0.75 }}>
      <Typography variant="body2" color="text.secondary">
        {label}
      </Typography>
      <Typography variant="body2" sx={{ fontWeight: 600, textAlign: "right", minWidth: 0 }}>
        {children}
      </Typography>
    </Stack>
  );
}

export default function CameraDetail() {
  const { cameraId } = useParams();
  const toast = useToast();
  const [testingAlert, setTestingAlert] = useState(false);

  const {
    data: camera,
    error: cameraError,
    loading: cameraLoading,
    refresh: refreshCamera,
  } = useAsync(({ signal }) => camerasApi.get(cameraId, { signal }), [cameraId]);

  // A camera with no worker answers 404 here, which is a normal state rather
  // than an error — so it is polled through the full status list instead of
  // the per-camera route, and simply absent when not monitored.
  const { data: statuses, refresh: refreshStatus } = usePolling(
    ({ signal }) => monitoring.statusAll({ signal }),
    { intervalMs: POLL_INTERVAL_MS, deps: [cameraId] }
  );

  const status = useMemo(
    () => (statuses || []).find((s) => String(s.camera_id) === String(cameraId)) || null,
    [statuses, cameraId]
  );

  const { data: eventPage, refresh: refreshEvents } = usePolling(
    ({ signal }) =>
      eventsApi.list({ camera_id: cameraId, limit: 10 }, { signal }),
    { intervalMs: 20000, deps: [cameraId] }
  );

  const refreshAll = useCallback(async () => {
    await Promise.all([refreshCamera(), refreshStatus(), refreshEvents()]);
  }, [refreshCamera, refreshStatus, refreshEvents]);

  const { busyId, start, stop, restart } = useMonitoringActions(refreshAll);
  const busy = busyId === Number(cameraId) || busyId === cameraId;

  const sendTestAlert = async () => {
    setTestingAlert(true);
    try {
      const rows = await alertsApi.test(Number(cameraId));
      toast.success(`Test alert dispatched on ${rows.length} channel(s).`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setTestingAlert(false);
    }
  };

  if (cameraLoading && !camera) return <Loading label="Loading camera…" height={340} />;

  if (cameraError && !camera) {
    return (
      <Box>
        <PageHeader title="Exit" />
        <ErrorState error={cameraError} onRetry={refreshCamera} />
        <Button component={RouterLink} to="/cameras" startIcon={<ArrowBackIcon />}>
          Back to exits
        </Button>
      </Box>
    );
  }

  const accessibility = Number(status?.accessibility_pct ?? 100);
  const running = Boolean(status);
  const needsZone = camera?.strategy === "zone_based" && !camera?.door_polygon?.length;

  return (
    <Box>
      <PageHeader
        title={camera?.name}
        subtitle={camera?.location || "No location set"}
        actions={
          <>
            <Button startIcon={<ArrowBackIcon />} component={RouterLink} to="/cameras" color="inherit">
              Back
            </Button>
            <Button
              startIcon={<CropFreeIcon />}
              component={RouterLink}
              to={`/cameras/${cameraId}/zone`}
              color="inherit"
            >
              Exit region
            </Button>
            <Button
              startIcon={<EditIcon />}
              component={RouterLink}
              to={`/cameras/${cameraId}/edit`}
              color="inherit"
            >
              Edit
            </Button>
            {running ? (
              <>
                <Button
                  startIcon={<RestartAltIcon />}
                  onClick={() => restart(Number(cameraId))}
                  disabled={busy}
                  color="inherit"
                >
                  Restart
                </Button>
                <Button
                  startIcon={<StopIcon />}
                  variant="outlined"
                  color="error"
                  onClick={() => stop(Number(cameraId))}
                  disabled={busy}
                >
                  Stop
                </Button>
              </>
            ) : (
              <Button
                startIcon={<PlayArrowIcon />}
                variant="contained"
                onClick={() => start(Number(cameraId))}
                disabled={busy}
              >
                Start monitoring
              </Button>
            )}
          </>
        }
      />

      {needsZone && (
        <Alert
          severity="warning"
          sx={{ mb: 2 }}
          action={
            <Button
              size="small"
              color="inherit"
              component={RouterLink}
              to={`/cameras/${cameraId}/zone`}
            >
              Draw it
            </Button>
          }
        >
          No exit region is defined. The zone-based strategy measures obstruction against a
          drawn polygon, so it has nothing to measure until you draw one.
        </Alert>
      )}

      {status?.error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {status.error}
        </Alert>
      )}
      {status?.warnings?.length > 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          {status.warnings.join(" · ")}
        </Alert>
      )}

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 7 }}>
          <Card>
            <LiveView cameraId={Number(cameraId)} height={420} />
            <CardContent>
              <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap alignItems="center">
                <StateChip state={status?.state || "UNKNOWN"} />
                <WorkerChip state={status?.worker_state || "stopped"} />
                <RiskChip level={status?.risk_level} score={status?.risk_score} />
                <StrategyChip strategy={status?.strategy || camera?.strategy} />
                {status?.door_visible === false && (
                  <Chip size="small" color="warning" label="door not visible" />
                )}
              </Stack>

              <Box sx={{ mt: 2.5 }}>
                <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
                  <Typography variant="body2" color="text.secondary">
                    Accessible
                  </Typography>
                  <Typography variant="body2" sx={{ fontWeight: 700 }}>
                    {status ? formatPct(accessibility) : "—"}
                  </Typography>
                </Stack>
                <LinearProgress
                  variant="determinate"
                  value={Math.max(0, Math.min(100, accessibility))}
                  color={BAR_COLOR[status?.state] || "inherit"}
                  sx={{ height: 10, borderRadius: 5 }}
                />
              </Box>

              {status?.recommended_action && (
                <Alert
                  severity={status.blocked ? "warning" : "success"}
                  sx={{ mt: 2 }}
                  icon={false}
                >
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    {status.recommended_action}
                  </Typography>
                </Alert>
              )}
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, lg: 5 }}>
          <Stack spacing={2}>
            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>
                  Right now
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <Field label="Blocked">{status?.blocked ? "Yes" : "No"}</Field>
                <Field label="Blocked for">
                  {status?.blocked ? formatDuration(status.blocked_duration_s) : "—"}
                </Field>
                <Field label="Blocked since">
                  {status?.blocked_since ? fromNow(status.blocked_since) : "—"}
                </Field>
                <Field label="People in view">{formatNumber(status?.people_count ?? 0)}</Field>
                <Field label="Open event">
                  {status?.event_id ? `#${status.event_id}` : "—"}
                </Field>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>
                  Blocking objects
                </Typography>
                <Divider sx={{ mb: 1 }} />
                {status?.blocking_objects?.length ? (
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Object</TableCell>
                        <TableCell align="right">Confidence</TableCell>
                        <TableCell align="right">Covers</TableCell>
                        <TableCell align="right">Track</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {status.blocking_objects.map((object, index) => (
                        <TableRow key={`${object.label}-${object.track_id ?? index}`}>
                          <TableCell>{object.label}</TableCell>
                          <TableCell align="right">
                            {formatPct(object.confidence * 100, 0)}
                          </TableCell>
                          <TableCell align="right">{formatPct(object.area_pct)}</TableCell>
                          <TableCell align="right">
                            {object.track_id ?? "—"}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <Typography variant="body2" color="text.secondary" sx={{ py: 1.5 }}>
                    Nothing is obstructing this exit.
                  </Typography>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>
                  Configuration
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <Field label="Source">
                  <Box
                    component="span"
                    sx={{ wordBreak: "break-all", fontSize: 12, fontWeight: 400 }}
                  >
                    {redactUrl(camera?.rtsp_url)}
                  </Box>
                </Field>
                <Field label="Strategy">{camera?.strategy}</Field>
                <Field label="Enabled">{camera?.enabled ? "Yes" : "No"}</Field>
                <Field label="Exit region">
                  {camera?.door_polygon?.length
                    ? `${camera.door_polygon.length} points`
                    : "not drawn"}
                </Field>
                <Field label="Reference captured">
                  {camera?.reference_captured_at
                    ? formatDateTime(camera.reference_captured_at)
                    : "—"}
                </Field>
                <Field label="CLEAR / FULL">
                  {`${camera?.clear_min_pct ?? "default"} / ${camera?.full_max_pct ?? "default"}`}
                </Field>
                <Field label="Confirm / clear">
                  {`${camera?.confirm_seconds ?? "default"}s / ${camera?.clear_seconds ?? "default"}s`}
                </Field>
                <Field label="Process FPS">{camera?.process_fps ?? "default"}</Field>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>
                  Pipeline
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <Field label="Frames processed">{formatNumber(status?.frames_processed)}</Field>
                <Field label="Effective FPS">
                  {status ? Number(status.fps ?? 0).toFixed(1) : "—"}
                </Field>
                <Field label="Inference">
                  {status ? `${Number(status.inference_ms ?? 0).toFixed(0)} ms` : "—"}
                </Field>
                <Field label="Reconnects">{formatNumber(status?.reconnects)}</Field>
                <Field label="Last frame">
                  {status?.last_frame_at ? fromNow(status.last_frame_at) : "—"}
                </Field>
                <Button
                  size="small"
                  startIcon={<NotificationsActiveIcon />}
                  onClick={sendTestAlert}
                  disabled={testingAlert}
                  sx={{ mt: 1.5 }}
                  fullWidth
                  variant="outlined"
                >
                  {testingAlert ? "Sending…" : "Send test alert"}
                </Button>
              </CardContent>
            </Card>
          </Stack>
        </Grid>

        <Grid size={12}>
          <Card>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="subtitle2">Recent blockage events</Typography>
                <Button size="small" component={RouterLink} to={`/events?camera_id=${cameraId}`}>
                  View all
                </Button>
              </Stack>
              <Divider sx={{ my: 1.5 }} />
              {eventPage?.items?.length ? (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Started</TableCell>
                      <TableCell>Duration</TableCell>
                      <TableCell>State</TableCell>
                      <TableCell>Peak</TableCell>
                      <TableCell align="right">Min accessible</TableCell>
                      <TableCell align="right">Peak risk</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {eventPage.items.map((event) => (
                      <TableRow key={event.id} hover>
                        <TableCell>{formatDateTime(event.started_at)}</TableCell>
                        <TableCell>
                          {event.ended_at ? formatDuration(event.duration_s) : (
                            <Chip size="small" color="warning" label="open" />
                          )}
                        </TableCell>
                        <TableCell>
                          <StateChip state={event.state} />
                        </TableCell>
                        <TableCell>
                          <StateChip state={event.peak_state} />
                        </TableCell>
                        <TableCell align="right">
                          {formatPct(event.min_accessibility_pct)}
                        </TableCell>
                        <TableCell align="right">
                          {Number(event.peak_risk_score ?? 0).toFixed(0)}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              ) : (
                <EmptyState
                  title="No blockage events recorded"
                  description="Events open only once an obstruction has persisted past the confirm window, so brief passers-by never appear here."
                />
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
