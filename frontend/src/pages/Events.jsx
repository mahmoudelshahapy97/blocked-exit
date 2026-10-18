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
import { formatDateTime, formatDuration, formatPct, summarizeObjects } from "../utils/format";

const ROWS_PER_PAGE = [10, 25, 50, 100];

const CONFIRM_WORD = "DELETE";

/** Admin-only: delete the events matching the filters, or every event. */
function DeleteDataDialog({ mode, filters, total, onClose, onDone }) {
  const toast = useToast();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const all = mode === "all";

  const submit = async () => {
    setBusy(true);
    try {
      const result = all ? await eventsApi.removeAll() : await eventsApi.remove(filters);
      toast.success(
        `Deleted ${result.deleted} event${result.deleted === 1 ? "" : "s"}` +
          (result.skipped_open ? `; kept ${result.skipped_open} still ongoing` : "")
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
      <DialogTitle>{all ? "Delete all events" : "Delete matching events"}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography variant="body2">
            {all
              ? "Every closed event in this workspace will be removed, with its alerts and snapshot."
              : `The ${total ?? ""} event${total === 1 ? "" : "s"} matching the current date, time, exit and location filters will be removed, with their alerts and snapshots.`}{" "}
            Ongoing blockages are kept. This cannot be undone.
          </Typography>
          {all && (
            <TextField
              size="small"
              label={`Type ${CONFIRM_WORD} to confirm`}
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              autoFocus
            />
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy} color="inherit">
          Cancel
        </Button>
        <Button
          color="error"
          variant="contained"
          onClick={submit}
          disabled={busy || (all && typed !== CONFIRM_WORD)}
        >
          Delete
        </Button>
      </DialogActions>
    </Dialog>
  );
}

/** Acknowledge or resolve one event, with an optional note. */
function ActionDialog({ action, event, onClose, onDone }) {
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
      toast.success(`Event #${event.id} ${updated.status}`);
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
        {resolving ? "Resolve" : "Acknowledge"} event #{event.id}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography variant="body2" color="text.secondary">
            {event.camera_name} · {formatDateTime(event.started_at)}
            {!event.ended_at && " · the exit is still blocked"}
          </Typography>
          <TextField
            label={resolving ? "Resolution note" : "Note"}
            placeholder={resolving ? "What was blocking it, and what was done" : "Optional"}
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
          Cancel
        </Button>
        <Button
          variant="contained"
          color={resolving ? "success" : "primary"}
          onClick={submit}
          disabled={busy}
        >
          {resolving ? "Resolve" : "Acknowledge"}
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
      .catch((err) => setSnapshotError(errorMessage(err)));
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
              Event #{event.id}
            </Typography>
            <EventStatusChip status={event.status} />
            <IconButton onClick={onClose} aria-label="Close">
              <CloseIcon />
            </IconButton>
          </Stack>

          {event.has_snapshot &&
            (snapshot ? (
              <Box
                component="img"
                src={snapshot}
                alt={`Snapshot of event ${event.id}`}
                sx={{ width: "100%", borderRadius: 1, mb: 2, display: "block" }}
              />
            ) : snapshotError ? (
              <Typography variant="caption" color="text.secondary" sx={{ display: "block", mb: 2 }}>
                {snapshotError}
              </Typography>
            ) : (
              <Loading label="Loading snapshot…" height={180} />
            ))}

          <Fact label="Exit">
            <Button
              size="small"
              component={RouterLink}
              to={`/cameras/${event.camera_id}`}
              sx={{ textTransform: "none", p: 0, minWidth: 0 }}
            >
              {event.camera_name}
            </Button>
          </Fact>
          <Fact label="Blocked">
            {formatDateTime(event.started_at)} →{" "}
            {event.ended_at ? formatDateTime(event.ended_at) : <Chip size="small" color="warning" label="ongoing" />}
          </Fact>
          <Fact label="Duration">{formatDuration(event.duration_s)}</Fact>
          <Fact label="Worst state">
            <StateChip state={event.peak_state} /> · {formatPct(event.min_accessibility_pct)} accessible at worst
          </Fact>
          <Fact label="Risk">
            <RiskChip level={event.risk_level} score={event.peak_risk_score} />
          </Fact>
          <Fact label="Detection confidence">
            {event.confidence == null
              ? "—"
              : `peak ${formatPct(event.confidence * 100)} · mean ${formatPct(event.avg_confidence * 100)}`}
          </Fact>
          <Fact label="Blocked by">
            {event.blocking_objects?.length
              ? event.blocking_objects
                  .map((o) => `${o.label} (${formatPct(o.area_pct)})`)
                  .join(", ")
              : "—"}
          </Fact>

          <Divider sx={{ my: 1.5 }} />
          <Fact label="Acknowledged">
            {event.acknowledged_at
              ? `${formatDateTime(event.acknowledged_at)} by ${event.acknowledged_by || "—"}`
              : "Not yet"}
          </Fact>
          <Fact label="Resolved">
            {event.resolved_at
              ? `${formatDateTime(event.resolved_at)} by ${event.resolved_by || "—"}`
              : "Not yet"}
          </Fact>
          {event.resolution_note && <Fact label="Note">{event.resolution_note}</Fact>}

          {canResolve && event.status !== EVENT_STATUS.RESOLVED && (
            <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
              {event.status === EVENT_STATUS.DETECTED && (
                <Button variant="outlined" startIcon={<DoneIcon />} onClick={() => onAction("acknowledge", event)}>
                  Acknowledge
                </Button>
              )}
              <Button
                variant="contained"
                color="success"
                startIcon={<DoneAllIcon />}
                onClick={() => onAction("resolve", event)}
              >
                Resolve
              </Button>
            </Stack>
          )}
        </Box>
      )}
    </Drawer>
  );
}

export default function Events() {
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
        title="Blockage events"
        subtitle="One row per confirmed obstruction episode. Acknowledge what you are handling, resolve it when the exit is safe."
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
              label={<Typography variant="body2">Auto</Typography>}
            />
            <Button startIcon={<RefreshIcon />} onClick={refresh} color="inherit">
              Refresh
            </Button>
            {canManage && (
              <Button
                color="error"
                startIcon={<DeleteSweepIcon />}
                onClick={(event) => setDeleteMenu(event.currentTarget)}
              >
                Delete data
              </Button>
            )}
          </>
        }
      />

      <Menu anchorEl={deleteMenu} open={Boolean(deleteMenu)} onClose={() => setDeleteMenu(null)}>
        <Tooltip
          title={hasFilters(filters) ? "" : "Set a date, time, exit or location filter first"}
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
              Delete events matching the filters
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
          Delete all events…
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
          {select("Status", status, "status", [
            ["", "Any status"],
            [`${EVENT_STATUS.DETECTED},${EVENT_STATUS.ACKNOWLEDGED}`, "Unresolved"],
            [EVENT_STATUS.DETECTED, "Detected"],
            [EVENT_STATUS.ACKNOWLEDGED, "Acknowledged"],
            [EVENT_STATUS.RESOLVED, "Resolved"],
          ])}
          {select("Risk", riskLevel, "risk_level", [
            ["", "Any risk"],
            [`${RISK_LEVEL.HIGH},${RISK_LEVEL.CRITICAL}`, "High or critical"],
            ...Object.values(RISK_LEVEL).map((v) => [v, v]),
          ])}
          {select("Worst state", state, "state", [
            ["", "Any"],
            [BLOCKAGE_STATE.PARTIAL, BLOCKAGE_STATE.PARTIAL],
            [BLOCKAGE_STATE.FULL, BLOCKAGE_STATE.FULL],
          ], 140)}
          {select("Sort", sort, "sort", [
            ["time", "Newest first"],
            ["risk", "Highest risk first"],
          ], 170)}
          <FormControlLabel
            control={
              <Switch
                checked={openOnly}
                onChange={(event) => setParam({ open_only: event.target.checked })}
              />
            }
            label="Still blocked only"
          />

          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="body2" color="text.secondary">
            {data ? `${data.total} event${data.total === 1 ? "" : "s"}` : ""}
          </Typography>
        </Stack>
      </Card>

      <ErrorState error={error} onRetry={refresh} title="Could not load events" />

      <Card>
        {loading && !data ? (
          <Loading label="Loading events…" />
        ) : items.length === 0 ? (
          <EmptyState
            title="No events match these filters"
            description="A blockage is only recorded once it has persisted past the confirm window, so short-lived obstructions never become events."
          />
        ) : (
          <>
            <TableContainer>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>#</TableCell>
                    <TableCell>Exit</TableCell>
                    <TableCell>Started</TableCell>
                    <TableCell>Duration</TableCell>
                    <TableCell>Worst</TableCell>
                    <TableCell>Risk</TableCell>
                    <TableCell align="right">Confidence</TableCell>
                    <TableCell>Blocked by</TableCell>
                    <TableCell>Status</TableCell>
                    <TableCell align="right">Actions</TableCell>
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
                      <TableCell>{event.camera_name || `Camera ${event.camera_id}`}</TableCell>
                      <TableCell>{formatDateTime(event.started_at)}</TableCell>
                      <TableCell>
                        {event.ended_at ? (
                          formatDuration(event.duration_s)
                        ) : (
                          <Chip size="small" color="warning" label="ongoing" />
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
                              <Tooltip title="Acknowledge">
                                <IconButton
                                  size="small"
                                  onClick={() => setPendingAction({ action: "acknowledge", event })}
                                >
                                  <DoneIcon fontSize="small" />
                                </IconButton>
                              </Tooltip>
                            )}
                            <Tooltip title="Resolve">
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
