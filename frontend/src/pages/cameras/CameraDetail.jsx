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
import NetworkCheckIcon from "@mui/icons-material/NetworkCheck";

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
import { useTranslation } from "react-i18next";
import { ProbeDialog, useProbe } from "@insighteye/ui";

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
  const { t } = useTranslation();
  const { cameraId } = useParams();
  const toast = useToast();
  const [testingAlert, setTestingAlert] = useState(false);
  const probe = useProbe(camerasApi, errorMessage);

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
      toast.success(t("cameraDetail.testAlertDispatchedOnLength", { length: rows.length }));
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setTestingAlert(false);
    }
  };

  if (cameraLoading && !camera) return <Loading label={t("cameraDetail.loadingCamera")} height={340} />;

  if (cameraError && !camera) {
    return (
      <Box>
        <PageHeader title={t("cameraDetail.exit")} />
        <ErrorState error={cameraError} onRetry={refreshCamera} />
        <Button component={RouterLink} to="/cameras" startIcon={<ArrowBackIcon />}>
          {t("cameraDetail.backToExits")}
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
        subtitle={camera?.location || t("cameraDetail.noLocationSet")}
        actions={
          <>
            <Button startIcon={<ArrowBackIcon />} component={RouterLink} to="/cameras" color="inherit">
              {t("cameraDetail.back")}
            </Button>
            <Button
              startIcon={<CropFreeIcon />}
              component={RouterLink}
              to={`/cameras/${cameraId}/zone`}
              color="inherit"
            >
              {t("cameraDetail.exitRegion")}
            </Button>
            <Button startIcon={<NetworkCheckIcon />} onClick={() => probe.probe(cameraId)} color="inherit">
              {t("actions.testConnection")}
            </Button>
            <Button
              startIcon={<EditIcon />}
              component={RouterLink}
              to={`/cameras/${cameraId}/edit`}
              color="inherit"
            >
              {t("cameraDetail.edit")}
            </Button>
            {running ? (
              <>
                <Button
                  startIcon={<RestartAltIcon />}
                  onClick={() => restart(Number(cameraId))}
                  disabled={busy}
                  color="inherit"
                >
                  {t("cameraDetail.restart")}
                </Button>
                <Button
                  startIcon={<StopIcon />}
                  variant="outlined"
                  color="error"
                  onClick={() => stop(Number(cameraId))}
                  disabled={busy}
                >
                  {t("cameraDetail.stop")}
                </Button>
              </>
            ) : (
              <Button
                startIcon={<PlayArrowIcon />}
                variant="contained"
                onClick={() => start(Number(cameraId))}
                disabled={busy}
              >
                {t("cameraDetail.startMonitoring")}
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
              {t("cameraDetail.drawIt")}
            </Button>
          }
        >
          {t("cameraDetail.noExitRegionIsDefined")}
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
                  <Chip size="small" color="warning" label={t("cameraDetail.doorNotVisible")} />
                )}
              </Stack>

              <Box sx={{ mt: 2.5 }}>
                <Stack direction="row" justifyContent="space-between" sx={{ mb: 0.5 }}>
                  <Typography variant="body2" color="text.secondary">
                    {t("cameraDetail.accessible")}
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
                    {/* One fixed sentence per risk level (services/risk.py). */}
                    {t(`cameraDetail.action.${status.risk_level}`, {
                      defaultValue: status.recommended_action,
                    })}
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
                  {t("cameraDetail.rightNow")}
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <Field label={t("cameraDetail.blocked")}>{status?.blocked ? t("cameraDetail.yes") : t("cameraDetail.no")}</Field>
                <Field label={t("cameraDetail.blockedFor")}>
                  {status?.blocked ? formatDuration(status.blocked_duration_s) : "—"}
                </Field>
                <Field label={t("cameraDetail.blockedSince")}>
                  {status?.blocked_since ? fromNow(status.blocked_since) : "—"}
                </Field>
                <Field label={t("cameraDetail.peopleInView")}>{formatNumber(status?.people_count ?? 0)}</Field>
                <Field label={t("cameraDetail.openEvent")}>
                  {status?.event_id ? `#${status.event_id}` : "—"}
                </Field>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>
                  {t("cameraDetail.blockingObjects")}
                </Typography>
                <Divider sx={{ mb: 1 }} />
                {status?.blocking_objects?.length ? (
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>{t("cameraDetail.object")}</TableCell>
                        <TableCell align="right">{t("cameraDetail.confidence")}</TableCell>
                        <TableCell align="right">{t("cameraDetail.covers")}</TableCell>
                        <TableCell align="right">{t("cameraDetail.track")}</TableCell>
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
                    {t("cameraDetail.nothingIsObstructingThisExit")}
                  </Typography>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>
                  {t("cameraDetail.configuration")}
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <Field label={t("cameraDetail.source")}>
                  <Box
                    component="span"
                    dir="ltr"
                    sx={{ wordBreak: "break-all", fontSize: 12, fontWeight: 400 }}
                  >
                    {redactUrl(camera?.rtsp_url)}
                  </Box>
                </Field>
                <Field label={t("cameraDetail.strategy")}>{camera?.strategy}</Field>
                <Field label={t("cameraDetail.enabled")}>{camera?.enabled ? t("cameraDetail.yes") : t("cameraDetail.no")}</Field>
                <Field label={t("cameraDetail.exitRegion")}>
                  {camera?.door_polygon?.length
                    ? t("cameraDetail.lengthPoints", { length: camera.door_polygon.length })
                    : t("cameraDetail.notDrawn")}
                </Field>
                <Field label={t("cameraDetail.referenceCaptured")}>
                  {camera?.reference_captured_at
                    ? formatDateTime(camera.reference_captured_at)
                    : "—"}
                </Field>
                <Field label={t("cameraDetail.clearFull")}>
                  {`${camera?.clear_min_pct ?? "default"} / ${camera?.full_max_pct ?? "default"}`}
                </Field>
                <Field label={t("cameraDetail.confirmClear")}>
                  {`${camera?.confirm_seconds ?? "default"}s / ${camera?.clear_seconds ?? "default"}s`}
                </Field>
                <Field label={t("cameraDetail.processFps")}>{camera?.process_fps ?? t("cameraDetail.default")}</Field>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <Typography variant="subtitle2" gutterBottom>
                  {t("cameraDetail.pipeline")}
                </Typography>
                <Divider sx={{ mb: 1 }} />
                <Field label={t("cameraDetail.framesProcessed")}>{formatNumber(status?.frames_processed)}</Field>
                <Field label={t("cameraDetail.effectiveFps")}>
                  {status ? Number(status.fps ?? 0).toFixed(1) : "—"}
                </Field>
                <Field label={t("cameraDetail.inference")}>
                  {status ? t("cameraDetail.v0Ms", { v0: Number(status.inference_ms ?? 0).toFixed(0) }) : "—"}
                </Field>
                <Field label={t("cameraDetail.reconnects")}>{formatNumber(status?.reconnects)}</Field>
                <Field label={t("cameraDetail.lastFrame")}>
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
                  {testingAlert ? t("cameraDetail.sending") : t("cameraDetail.sendTestAlert")}
                </Button>
              </CardContent>
            </Card>
          </Stack>
        </Grid>

        <Grid size={12}>
          <Card>
            <CardContent>
              <Stack direction="row" justifyContent="space-between" alignItems="center">
                <Typography variant="subtitle2">{t("cameraDetail.recentBlockageEvents")}</Typography>
                <Button size="small" component={RouterLink} to={`/events?camera_id=${cameraId}`}>
                  {t("cameraDetail.viewAll")}
                </Button>
              </Stack>
              <Divider sx={{ my: 1.5 }} />
              {eventPage?.items?.length ? (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>{t("cameraDetail.started")}</TableCell>
                      <TableCell>{t("cameraDetail.duration")}</TableCell>
                      <TableCell>{t("cameraDetail.state")}</TableCell>
                      <TableCell>{t("cameraDetail.peak")}</TableCell>
                      <TableCell align="right">{t("cameraDetail.minAccessible")}</TableCell>
                      <TableCell align="right">{t("cameraDetail.peakRisk")}</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {eventPage.items.map((event) => (
                      <TableRow key={event.id} hover>
                        <TableCell>{formatDateTime(event.started_at)}</TableCell>
                        <TableCell>
                          {event.ended_at ? formatDuration(event.duration_s) : (
                            <Chip size="small" color="warning" label={t("cameraDetail.open")} />
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
                  title={t("cameraDetail.noBlockageEventsRecorded")}
                  description={t("cameraDetail.eventsOpenOnlyOnceAn")}
                />
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
      <ProbeDialog {...probe.dialogProps} />
    </Box>
  );
}
