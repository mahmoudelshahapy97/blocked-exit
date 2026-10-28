import { useCallback, useEffect, useMemo, useState } from "react";
import { Link as RouterLink, useSearchParams } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import FormControlLabel from "@mui/material/FormControlLabel";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
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
import RefreshIcon from "@mui/icons-material/Refresh";
import DeleteSweepIcon from "@mui/icons-material/DeleteSweep";
import CloseIcon from "@mui/icons-material/Close";
import DoneIcon from "@mui/icons-material/Done";
import DoneAllIcon from "@mui/icons-material/DoneAll";

import { errorMessage } from "../api/client";
import { events as eventsApi } from "../api/endpoints";
import { usePolling } from "../hooks/usePolling";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../components/Toast";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import EventFilterBar, { FILTER_KEYS, hasFilters, pickFilters } from "../components/EventFilterBar";
import PageHeader from "../components/PageHeader";
import { EventStatusChip, RiskChip, StateChip } from "../components/StatusChips";
import { BLOCKAGE_STATE, EVENT_STATUS, RISK_LEVEL } from "../utils/constants";
import { formatDateTime, formatDuration, formatPct, summarizeObjects, titleCase } from "../utils/format";
import { useTranslation } from "react-i18next";
import { ExportButton } from "@insighteye/ui";

const ROWS_PER_PAGE = [10, 25, 50, 100];

const CONFIRM_WORD = "DELETE";

/** Admin-only: delete the events matching the filters, or every event. */
function DeleteDataDialog({ mode, filters, total, onClose, onDone }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const all = mode === "all";

  const submit = async () => {
    setBusy(true);
    try {
      const result = all ? await eventsApi.removeAll() : await eventsApi.remove(filters);
      toast.success(
        t("events.deletedCount", { count: result.deleted }) +
          (result.skipped_open ? t("events.keptOngoing", { kept: result.skipped_open }) : "")
      );
      onDone();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{all ? t("events.deleteAllEvents") : t("events.deleteMatchingEvents")}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography variant="body2">
            {t("events.v0OngoingBlockagesAreKept", { v0: all
              ? t("events.deleteAllBody")
              : t("events.deleteMatchingBody", { count: total ?? 0 }) })}
          </Typography>
          {all && (
            <TextField
              size="small"
              label={t("events.typeConfirmWordToConfirm", { CONFIRM_WORD })}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoFocus
            />
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy} color="inherit">
          {t("events.cancel")}
        </Button>
        <Button
          color="error"
          variant="contained"
          onClick={submit}
          disabled={busy || (all && typed !== CONFIRM_WORD)}
        >
          {t("events.delete")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/** Acknowledge or resolve one event, with an optional note. */
function ActionDialog({ action, event, onClose, onDone }) {
  const { t } = useTranslation();
  const toast = useToast();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const resolving = action === "resolve";

  const submit = async () => {
    setBusy(true);
    try {
      const updated = resolving
        ? await eventsApi.resolve(event.id, note)
        : await eventsApi.acknowledge(event.id, note);
      toast.success(t("events.eventIdStatus", { id: event.id, status: updated.status }));
      onDone(updated);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={busy ? undefined : onClose} maxWidth="xs" fullWidth>
      <DialogTitle>
        {t("events.v0EventId", { v0: resolving ? "Resolve" : "Acknowledge", id: event.id })}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {event.camera_name} · {formatDateTime(event.started_at)}
            {!event.ended_at && t("events.theExitIsStillBlocked")}
          </Typography>
          <TextField
            label={resolving ? t("events.resolutionNote") : t("events.note")}
            placeholder={resolving ? t("events.whatWasBlockingItAnd") : t("events.optional")}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            multiline
            minRows={2}
            inputProps={{ maxLength: 1000 }}
            autoFocus
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy} color="inherit">
          {t("events.cancel")}
        </Button>
        <Button
          variant="contained"
          color={resolving ? "success" : "primary"}
          onClick={submit}
          disabled={busy}
        >
          {resolving ? t("events.resolve") : t("events.acknowledge")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function Fact({ label, children }) {
  return (
    <Stack direction="row" spacing={2} sx={{ py: 0.75 }}>
      <Typography variant="body2" color="text.secondary" sx={{ minWidth: 140 }}>
        {label}
      </Typography>
      <Box sx={{ typography: "body2", minWidth: 0 }}>{children}</Box>
    </Stack>
  );
}

/** One event: its snapshot, what blocked the exit, and who handled it. */
function EventDrawer({ event, onClose, onAction, canResolve }) {
  const { t } = useTranslation();
  const [snapshot, setSnapshot] = useState(null);
  const [snapshotError, setSnapshotError] = useState(null);

  useEffect(() => {
    if (!event?.has_snapshot) return undefined;
    const controller = new AbortController();
    let url = null;
    eventsApi
      .snapshot(event.id, { signal: controller.signal })
      .then((objectUrl) => {
        url = objectUrl;
        setSnapshot(objectUrl);
      })
      .catch((err) => {
        // A blob response hides the server's JSON message; say what a 404 means.
        if (err?.response?.status === 404) {
          setSnapshotError("Snapshot no longer available (retention may have removed it).");
        } else {
          setSnapshotError(errorMessage(err));
        }
      });
    return () => {
      controller.abort();
      if (url) URL.revokeObjectURL(url);
      setSnapshot(null);
      setSnapshotError(null);
    };
  }, [event?.id, event?.has_snapshot]);

  return (
    <Drawer anchor="right" open={Boolean(event)} onClose={onClose}>
      {event && (
        <Box sx={{ width: { xs: "100vw", sm: 460 }, p: 2.5 }}>
          <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 2 }}>
            <Typography variant="h6" sx={{ flexGrow: 1 }}>
              {t("events.eventId", { id: event.id })}
            </Typography>
            <EventStatusChip status={event.status} />
            <IconButton onClick={onClose} aria-label={t("events.close")}>
              <CloseIcon />
            </IconButton>
          </Stack>

          {event.has_snapshot &&
            (snapshot ? (
              <Box
                component="img"
                src={snapshot}
                alt={t("events.snapshotOfEventId", { id: event.id })}
                sx={{ width: "100%", borderRadius: 1, mb: 2, display: "block" }}
              />
            ) : snapshotError ? (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 2 }}>
                {snapshotError}
              </Typography>
            ) : (
              <Loading label={t("events.loadingSnapshot")} height={180} />
            ))}

          <Fact label={t("events.exit")}>
            <Button
              size="small"
              component={RouterLink}
              to={`/cameras/${event.camera_id}`}
              sx={{ textTransform: "none", p: 0, minWidth: 0 }}
            >
              {event.camera_name}
            </Button>
          </Fact>
          <Fact label={t("events.blocked")}>
            {formatDateTime(event.started_at)} →{" "}
            {event.ended_at ? formatDateTime(event.ended_at) : <Chip size="small" color="warning" label={t("events.ongoing")} />}
          </Fact>
          <Fact label={t("events.duration")}>{formatDuration(event.duration_s)}</Fact>
          <Fact label={t("events.worstState")}>
            <StateChip state={event.peak_state} /> · {formatPct(event.min_accessibility_pct)}{" "}{t("events.accessibleAtWorst")}
          </Fact>
          <Fact label={t("events.risk")}>
            <RiskChip level={event.risk_level} score={event.peak_risk_score} />
          </Fact>
          <Fact label={t("events.detectionConfidence")}>
            {event.confidence == null
              ? "—"
              : t("events.peakV0MeanV1", { v0: formatPct(event.confidence * 100), v1: formatPct(event.avg_confidence * 100) })}
          </Fact>
          <Fact label={t("events.blockedBy")}>
            {event.blocking_objects?.length
              ? event.blocking_objects
                  .map((o) => `${o.label} (${formatPct(o.area_pct)})`)
                  .join(", ")
              : "—"}
          </Fact>

          <Divider sx={{ my: 1.5 }} />
          <Fact label={t("events.acknowledged")}>
            {event.acknowledged_at
              ? t("events.v0ByV1", { v0: formatDateTime(event.acknowledged_at), v1: event.acknowledged_by || "—" })
              : t("events.notYet")}
          </Fact>
          <Fact label={t("events.resolved")}>
            {event.resolved_at
              ? t("events.v0ByV1", { v0: formatDateTime(event.resolved_at), v1: event.resolved_by || "—" })
              : t("events.notYet")}
          </Fact>
          {event.resolution_note && <Fact label={t("events.note")}>{event.resolution_note}</Fact>}

          {canResolve && event.status !== EVENT_STATUS.RESOLVED && (
            <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
              {event.status === EVENT_STATUS.DETECTED && (
                <Button variant="outlined" startIcon={<DoneIcon />} onClick={() => onAction("acknowledge", event)}>
                  {t("events.acknowledge")}
                </Button>
              )}
              <Button
                variant="contained"
                color="success"
                startIcon={<DoneAllIcon />}
                onClick={() => onAction("resolve", event)}
              >
                {t("events.resolve")}
              </Button>
            </Stack>
          )}
        </Box>
      )}
    </Drawer>
  );
}

export default function Events() {
  const { t } = useTranslation();
  // Filters live in the URL so a view worth sharing is a link, and the "View
  // all" button on a camera page can arrive here pre-filtered.
  const [searchParams, setSearchParams] = useSearchParams();

  const filters = useMemo(() => pickFilters(searchParams), [searchParams]);
  const status = searchParams.get("status") || "";
  const riskLevel = searchParams.get("risk_level") || "";
  const state = searchParams.get("state") || "";
  const sort = searchParams.get("sort") || "time";
  const openOnly = searchParams.get("open_only") === "true";
  const limit = Number(searchParams.get("limit")) || 25;
  const offset = Number(searchParams.get("offset")) || 0;

  const [autoRefresh, setAutoRefresh] = useState(true);
  const { canManage, canResolve } = useAuth();
  const [deleteMenu, setDeleteMenu] = useState(null);
  const [deleteMode, setDeleteMode] = useState(null); // "filtered" | "all"
  const [selected, setSelected] = useState(null);
  const [pendingAction, setPendingAction] = useState(null); // { action, event }

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
        // Any filter change invalidates the current page.
        if (!("offset" in updates)) next.delete("offset");
        return next;
      });
    },
    [setSearchParams]
  );

  const setFilters = useCallback(
    (next) =>
      setParam(Object.fromEntries(FILTER_KEYS.map((key) => [key, next[key] || ""]))),
    [setParam]
  );

  const params = useMemo(
    () => ({
      limit,
      offset,
      ...filters,
      ...(status ? { status } : {}),
      ...(riskLevel ? { risk_level: riskLevel } : {}),
      ...(state ? { state } : {}),
      ...(sort !== "time" ? { sort } : {}),
      ...(openOnly ? { open_only: true } : {}),
    }),
    [limit, offset, filters, status, riskLevel, state, sort, openOnly]
  );

  const { data, error, loading, refresh } = usePolling(
    ({ signal }) => eventsApi.list(params, { signal }),
    { intervalMs: autoRefresh ? 15000 : 0, deps: [JSON.stringify(params), autoRefresh] }
  );

  const items = data?.items || [];

  const onActionDone = (updated) => {
    setPendingAction(null);
    if (selected?.id === updated.id) setSelected(updated);
    refresh();
  };

  const select = (label, value, key, options, width = 170) => (
    <TextField
      select
      size="small"
      label={label}
      value={value}
      onChange={(event) => setParam({ [key]: event.target.value })}
      sx={{ minWidth: width }}
    >
      {options.map(([optionValue, optionLabel]) => (
        <MenuItem key={optionValue} value={optionValue}>
          {optionLabel}
        </MenuItem>
      ))}
    </TextField>
  );

  return (
    <Box>
      <PageHeader
        title={t("events.blockageEvents")}
        subtitle={t("events.oneRowPerConfirmedObstruction")}
        actions={
          <>
            <FormControlLabel
              control={
                <Switch
                  size="small"
                  checked={autoRefresh}
                  onChange={(event) => setAutoRefresh(event.target.checked)}
                />
              }
              label={<Typography variant="body2">{t("events.auto")}</Typography>}
            />
            <Button startIcon={<RefreshIcon />} onClick={refresh} color="inherit">
              {t("events.refresh")}
            </Button>
            <ExportButton
              fetchBlob={() => {
                // The list's filters, without its paging and sort.
                const { limit: _limit, offset: _offset, sort: _sort, ...rest } = params;
                return eventsApi.exportBlob(rest);
              }}
              filenameStem="blockage-events"
            />
            {canManage && (
              <Button
                color="error"
                startIcon={<DeleteSweepIcon />}
                onClick={(event) => setDeleteMenu(event.currentTarget)}
              >
                {t("events.deleteData")}
              </Button>
            )}
          </>
        }
      />

      <Menu anchorEl={deleteMenu} open={Boolean(deleteMenu)} onClose={() => setDeleteMenu(null)}>
        <Tooltip
          title={hasFilters(filters) ? "" : t("events.setADateTimeExit")}
          placement="left"
        >
          <span>
            <MenuItem
              disabled={!hasFilters(filters)}
              onClick={() => {
                setDeleteMode("filtered");
                setDeleteMenu(null);
              }}
            >
              {t("events.deleteEventsMatchingTheFilters")}
            </MenuItem>
          </span>
        </Tooltip>
        <Divider />
        <MenuItem
          sx={{ color: "error.main" }}
          onClick={() => {
            setDeleteMode("all");
            setDeleteMenu(null);
          }}
        >
          {t("events.deleteAllEvents2")}
        </MenuItem>
      </Menu>
      {deleteMode && (
        <DeleteDataDialog
          mode={deleteMode}
          filters={filters}
          total={data?.total}
          onClose={() => setDeleteMode(null)}
          onDone={() => {
            setDeleteMode(null);
            refresh();
          }}
        />
      )}

      <Card sx={{ p: 2, mb: 2 }}>
        <EventFilterBar value={filters} onChange={setFilters} />
        <Divider sx={{ my: 2 }} />
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={2}
          alignItems={{ md: "center" }}
          flexWrap="wrap"
          useFlexGap
        >
          {select(t("events.status"), status, "status", [
            ["", t("events.anyStatus")],
            [`${EVENT_STATUS.DETECTED},${EVENT_STATUS.ACKNOWLEDGED}`, t("events.unresolved")],
            [EVENT_STATUS.DETECTED, titleCase(EVENT_STATUS.DETECTED)],
            [EVENT_STATUS.ACKNOWLEDGED, titleCase(EVENT_STATUS.ACKNOWLEDGED)],
            [EVENT_STATUS.RESOLVED, titleCase(EVENT_STATUS.RESOLVED)],
          ])}
          {select(t("events.risk"), riskLevel, "risk_level", [
            ["", t("events.anyRisk")],
            [`${RISK_LEVEL.HIGH},${RISK_LEVEL.CRITICAL}`, t("events.highOrCritical")],
            ...Object.values(RISK_LEVEL).map((v) => [v, titleCase(v)]),
          ])}
          {select(t("events.worstState"), state, "state", [
            ["", t("events.any")],
            [BLOCKAGE_STATE.PARTIAL, titleCase(BLOCKAGE_STATE.PARTIAL)],
            [BLOCKAGE_STATE.FULL, titleCase(BLOCKAGE_STATE.FULL)],
          ], 140)}
          {select(t("events.sort"), sort, "sort", [
            ["time", t("events.newestFirst")],
            ["risk", t("events.highestRiskFirst")],
          ], 170)}
          <FormControlLabel
            control={
              <Switch
                checked={openOnly}
                onChange={(event) => setParam({ open_only: event.target.checked })}
              />
            }
            label={t("events.stillBlockedOnly")}
          />

          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="body2" color="text.secondary">
            {data ? t("events.totalEvents", { count: data.total }) : ""}
          </Typography>
        </Stack>
      </Card>

      <ErrorState error={error} onRetry={refresh} title={t("events.couldNotLoadEvents")} />

      <Card>
        {loading && !data ? (
          <Loading label={t("events.loadingEvents")} />
        ) : items.length === 0 ? (
          <EmptyState
            title={t("events.noEventsMatchTheseFilters")}
            description={t("events.aBlockageIsOnlyRecorded")}
          />
        ) : (
          <>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>#</TableCell>
                    <TableCell>{t("events.exit")}</TableCell>
                    <TableCell>{t("events.started")}</TableCell>
                    <TableCell>{t("events.duration")}</TableCell>
                    <TableCell>{t("events.worst")}</TableCell>
                    <TableCell>{t("events.risk")}</TableCell>
                    <TableCell align="right">{t("events.confidence")}</TableCell>
                    <TableCell>{t("events.blockedBy")}</TableCell>
                    <TableCell>{t("events.status")}</TableCell>
                    <TableCell align="right">{t("events.actions")}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((event) => (
                    <TableRow
                      key={event.id}
                      hover
                      sx={{ cursor: "pointer" }}
                      onClick={() => setSelected(event)}
                    >
                      <TableCell>{event.id}</TableCell>
                      <TableCell>{event.camera_name || t("events.cameraCameraId", { camera_id: event.camera_id })}</TableCell>
                      <TableCell>{formatDateTime(event.started_at)}</TableCell>
                      <TableCell>
                        {event.ended_at ? (
                          formatDuration(event.duration_s)
                        ) : (
                          <Chip size="small" color="warning" label={t("events.ongoing")} />
                        )}
                      </TableCell>
                      <TableCell>
                        <StateChip state={event.peak_state} />
                      </TableCell>
                      <TableCell>
                        <RiskChip level={event.risk_level} score={event.peak_risk_score} />
                      </TableCell>
                      <TableCell align="right">
                        {event.confidence == null ? "—" : formatPct(event.confidence * 100, 0)}
                      </TableCell>
                      <TableCell>
                        <Tooltip
                          title={
                            event.blocking_objects
                              ?.map((o) => `${o.label} (${formatPct(o.area_pct)})`)
                              .join(", ") || ""
                          }
                        >
                          <span>{summarizeObjects(event.blocking_objects)}</span>
                        </Tooltip>
                      </TableCell>
                      <TableCell>
                        <EventStatusChip status={event.status} />
                      </TableCell>
                      <TableCell align="right" onClick={(e) => e.stopPropagation()}>
                        {canResolve && event.status !== EVENT_STATUS.RESOLVED && (
                          <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                            {event.status === EVENT_STATUS.DETECTED && (
                              <Tooltip title={t("events.acknowledge")}>
                                <IconButton
                                  size="small"
                                  onClick={() => setPendingAction({ action: "acknowledge", event })}
                                >
                                  <DoneIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}
                            <Tooltip title={t("events.resolve")}>
                              <IconButton
                                size="small"
                                color="success"
                                onClick={() => setPendingAction({ action: "resolve", event })}
                              >
                                <DoneAllIcon fontSize="small" />
                              </IconButton>
                            </Tooltip>
                          </Stack>
                        )}
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
              rowsPerPageOptions={ROWS_PER_PAGE}
              onPageChange={(_, page) => setParam({ offset: page * limit })}
              onRowsPerPageChange={(event) =>
                setParam({ limit: event.target.value, offset: 0 })
              }
            />
          </>
        )}
      </Card>

      <EventDrawer
        event={selected}
        canResolve={canResolve}
        onClose={() => setSelected(null)}
        onAction={(action, event) => setPendingAction({ action, event })}
      />
      {pendingAction && (
        <ActionDialog
          action={pendingAction.action}
          event={pendingAction.event}
          onClose={() => setPendingAction(null)}
          onDone={onActionDone}
        />
      )}
    </Box>
  );
}
