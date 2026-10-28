import { useCallback, useMemo, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TablePagination from "@mui/material/TablePagination";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import CheckCircleIcon from "@mui/icons-material/CheckCircle";
import CodeIcon from "@mui/icons-material/Code";
import RefreshIcon from "@mui/icons-material/Refresh";

import { errorMessage } from "../api/client";
import { alerts as alertsApi, cameras as camerasApi } from "../api/endpoints";
import { usePolling } from "../hooks/usePolling";
import { useAsync } from "../hooks/useAsync";
import { useToast } from "../components/Toast";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import PageHeader from "../components/PageHeader";
import { ALERT_CHANNEL, ALERT_STATUS } from "../utils/constants";
import { formatDateTime, fromNow } from "../utils/format";
import { useTranslation } from "react-i18next";

const STATUS_COLOR = {
  sent: "success",
  pending: "info",
  failed: "error",
  skipped: "default",
};

function AcknowledgeDialog({ alert, onClose, onDone }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [name, setName] = useState(() => localStorage.getItem("blocked-exit:ack-name") || "");
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!name.trim()) return;
    setBusy(true);
    try {
      await alertsApi.acknowledge(alert.id, name.trim());
      // Remembered because the same operator acknowledges many alerts in a
      // shift and retyping their name each time is pure friction.
      localStorage.setItem("blocked-exit:ack-name", name.trim());
      toast.success(t("alerts.alertIdAcknowledged", { id: alert.id }));
      onDone();
      onClose();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={Boolean(alert)} onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t("alerts.acknowledgeAlertV0", { v0: alert?.id })}</DialogTitle>
      <DialogContent>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
          {t("alerts.recordedAgainstThisAlertSo")}
        </Typography>
        <TextField
          autoFocus
          fullWidth
          label={t("alerts.yourName")}
          value={name}
          onChange={(event) => setName(event.target.value)}
          onKeyDown={(event) => event.key === "Enter" && submit()}
        />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose} color="inherit" disabled={busy}>
          {t("alerts.cancel")}
        </Button>
        <Button onClick={submit} variant="contained" disabled={busy || !name.trim()}>
          {busy ? t("alerts.saving") : t("alerts.acknowledge")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function PayloadDialog({ alert, onClose }) {
  const { t } = useTranslation();
  return (
    <Dialog open={Boolean(alert)} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>{t("alerts.alertV0Payload", { v0: alert?.id })}</DialogTitle>
      <DialogContent>
        {alert?.error && (
          <Typography variant="body2" color="error.main" sx={{ mb: 2 }}>
            {alert.error}
          </Typography>
        )}
        <Box
          component="pre"
          sx={{
            m: 0,
            p: 2,
            borderRadius: 2,
            bgcolor: (t) => (t.palette.mode === "dark" ? "#05070d" : "grey.100"),
            fontSize: 12,
            overflow: "auto",
            maxHeight: "60vh",
          }}
        >
          {JSON.stringify(alert?.payload ?? {}, null, 2)}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("alerts.close")}</Button>
      </DialogActions>
    </Dialog>
  );
}

export default function Alerts() {
  const { t } = useTranslation();
  const [searchParams, setSearchParams] = useSearchParams();
  const [acknowledging, setAcknowledging] = useState(null);
  const [viewing, setViewing] = useState(null);

  const cameraId = searchParams.get("camera_id") || "";
  const status = searchParams.get("status") || "";
  const channel = searchParams.get("channel") || "";
  const unackOnly = searchParams.get("unacknowledged_only") === "true";
  const limit = Number(searchParams.get("limit")) || 25;
  const offset = Number(searchParams.get("offset")) || 0;

  const setParam = useCallback(
    (updates) => {
      setSearchParams((current) => {
        const next = new URLSearchParams(current);
        Object.entries(updates).forEach(([key, value]) => {
          if (value === "" || value === null || value === undefined || value === false) {
            next.delete(key);
          } else {
            next.set(key, String(value));
          }
        });
        if (!("offset" in updates)) next.delete("offset");
        return next;
      });
    },
    [setSearchParams]
  );

  const { data: cameraList } = useAsync(({ signal }) => camerasApi.list(undefined, { signal }), []);

  const params = useMemo(
    () => ({
      limit,
      offset,
      ...(cameraId ? { camera_id: Number(cameraId) } : {}),
      ...(status ? { status } : {}),
      ...(channel ? { channel } : {}),
      ...(unackOnly ? { unacknowledged_only: true } : {}),
    }),
    [limit, offset, cameraId, status, channel, unackOnly]
  );

  const { data, error, loading, refresh } = usePolling(
    ({ signal }) => alertsApi.list(params, { signal }),
    { intervalMs: 15000, deps: [JSON.stringify(params)] }
  );

  const cameraNames = useMemo(
    () => new Map((cameraList || []).map((camera) => [camera.id, camera.name])),
    [cameraList]
  );

  const items = data?.items || [];

  return (
    <Box>
      <PageHeader
        title={t("alerts.alerts")}
        subtitle={t("alerts.deliveryAttemptsPerChannelNothing")}
        actions={
          <Button startIcon={<RefreshIcon />} onClick={refresh} color="inherit">
            {t("alerts.refresh")}
          </Button>
        }
      />

      <Card sx={{ p: 2, mb: 2 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>
          <TextField
            select
            size="small"
            label={t("alerts.exit")}
            value={cameraId}
            onChange={(event) => setParam({ camera_id: event.target.value })}
            sx={{ minWidth: 200 }}
          >
            <MenuItem value="">{t("alerts.allExits")}</MenuItem>
            {(cameraList || []).map((camera) => (
              <MenuItem key={camera.id} value={camera.id}>
                {camera.name}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            size="small"
            label={t("alerts.status")}
            value={status}
            onChange={(event) => setParam({ status: event.target.value })}
            sx={{ minWidth: 150 }}
          >
            <MenuItem value="">{t("alerts.anyStatus")}</MenuItem>
            {Object.values(ALERT_STATUS).map((value) => (
              <MenuItem key={value} value={value}>
                {value}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            size="small"
            label={t("alerts.channel")}
            value={channel}
            onChange={(event) => setParam({ channel: event.target.value })}
            sx={{ minWidth: 150 }}
          >
            <MenuItem value="">{t("alerts.anyChannel")}</MenuItem>
            {Object.values(ALERT_CHANNEL).map((value) => (
              <MenuItem key={value} value={value}>
                {value}
              </MenuItem>
            ))}
          </TextField>

          <FormControlLabel
            control={
              <Switch
                checked={unackOnly}
                onChange={(event) => setParam({ unacknowledged_only: event.target.checked })}
              />
            }
            label={t("alerts.unacknowledgedOnly")}
          />

          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="body2" color="text.secondary">
            {data ? t("alerts.totalAlerts", { count: data.total }) : ""}
          </Typography>
        </Stack>
      </Card>

      <ErrorState error={error} onRetry={refresh} title={t("alerts.couldNotLoadAlerts")} />

      <Card>
        {loading && !data ? (
          <Loading label={t("alerts.loadingAlerts")} />
        ) : items.length === 0 ? (
          <EmptyState
            title={t("alerts.noAlertsMatchTheseFilters")}
            description={t("alerts.alertsNeedADeliveryChannel")}
          />
        ) : (
          <>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>#</TableCell>
                    <TableCell>{t("alerts.exit")}</TableCell>
                    <TableCell>{t("alerts.event")}</TableCell>
                    <TableCell>{t("alerts.channel")}</TableCell>
                    <TableCell>{t("alerts.status")}</TableCell>
                    <TableCell>{t("alerts.created")}</TableCell>
                    <TableCell>{t("alerts.sent")}</TableCell>
                    <TableCell>{t("alerts.acknowledged")}</TableCell>
                    <TableCell align="right">{t("alerts.actions")}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((alert) => (
                    <TableRow key={alert.id} hover>
                      <TableCell>{alert.id}</TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          component={RouterLink}
                          to={`/cameras/${alert.camera_id}`}
                          sx={{ textTransform: "none", p: 0, minWidth: 0 }}
                        >
                          {cameraNames.get(alert.camera_id) || t("alerts.cameraCameraId", { camera_id: alert.camera_id })}
                        </Button>
                      </TableCell>
                      <TableCell>
                        {alert.event_id ? (
                          <RouterLink to={`/events?camera_id=${alert.camera_id}`}>
                            #{alert.event_id}
                          </RouterLink>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell>
                        <Chip size="small" variant="outlined" label={alert.channel} />
                      </TableCell>
                      <TableCell>
                        <Tooltip title={alert.error || ""}>
                          <Chip
                            size="small"
                            color={STATUS_COLOR[alert.status] || "default"}
                            label={alert.status}
                          />
                        </Tooltip>
                      </TableCell>
                      <TableCell>
                        <Tooltip title={formatDateTime(alert.created_at)}>
                          <span>{fromNow(alert.created_at)}</span>
                        </Tooltip>
                      </TableCell>
                      <TableCell>{alert.sent_at ? fromNow(alert.sent_at) : "—"}</TableCell>
                      <TableCell>
                        {alert.acknowledged_at ? (
                          <Tooltip title={formatDateTime(alert.acknowledged_at)}>
                            <Chip
                              size="small"
                              color="success"
                              variant="outlined"
                              label={alert.acknowledged_by || t("alerts.acknowledged2")}
                            />
                          </Tooltip>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell align="right">
                        <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                          <Tooltip title={t("alerts.viewPayload")}>
                            <IconButton size="small" onClick={() => setViewing(alert)}>
                              <CodeIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                          <Tooltip
                            title={
                              alert.acknowledged_at ? t("alerts.alreadyAcknowledged") : t("alerts.acknowledge")
                            }
                          >
                            <span>
                              <IconButton
                                size="small"
                                color="success"
                                disabled={Boolean(alert.acknowledged_at)}
                                onClick={() => setAcknowledging(alert)}
                              >
                                <CheckCircleIcon fontSize="small" />
                              </IconButton>
                            </span>
                          </Tooltip>
                        </Stack>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>

            <TablePagination
              component="div"
              count={data?.total || 0}
              page={Math.floor(offset / limit)}
              rowsPerPage={limit}
              rowsPerPageOptions={[10, 25, 50, 100]}
              onPageChange={(_, page) => setParam({ offset: page * limit })}
              onRowsPerPageChange={(event) => setParam({ limit: event.target.value, offset: 0 })}
            />
          </>
        )}
      </Card>

      {acknowledging && (
        <AcknowledgeDialog
          alert={acknowledging}
          onClose={() => setAcknowledging(null)}
          onDone={refresh}
        />
      )}
      {viewing && <PayloadDialog alert={viewing} onClose={() => setViewing(null)} />}
    </Box>
  );
}
