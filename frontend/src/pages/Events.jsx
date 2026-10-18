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
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
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

import { errorMessage } from "../api/client";
import { cameras as camerasApi, events as eventsApi } from "../api/endpoints";
import { usePolling } from "../hooks/usePolling";
import { useAsync } from "../hooks/useAsync";
import { useAuth } from "../context/AuthContext";
import { useToast } from "../components/Toast";
import { EmptyState, ErrorState, Loading } from "../components/DataStates";
import EventFilterBar, { FILTER_KEYS, hasFilters, pickFilters } from "../components/EventFilterBar";
import PageHeader from "../components/PageHeader";
import { StateChip } from "../components/StatusChips";
import { BLOCKAGE_STATE } from "../utils/constants";
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

export default function Events() {
  // Filters live in the URL so a view worth sharing is a link, and the "View
  // all" button on a camera page can arrive here pre-filtered.
  const [searchParams, setSearchParams] = useSearchParams();

  const filters = useMemo(() => pickFilters(searchParams), [searchParams]);
  const state = searchParams.get("state") || "";
  const openOnly = searchParams.get("open_only") === "true";
  const limit = Number(searchParams.get("limit")) || 25;
  const offset = Number(searchParams.get("offset")) || 0;

  const [autoRefresh, setAutoRefresh] = useState(true);
  const { canManage } = useAuth();
  const [deleteMenu, setDeleteMenu] = useState(null);
  const [deleteMode, setDeleteMode] = useState(null); // "filtered" | "all"

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

  const { data: cameraList } = useAsync(({ signal }) => camerasApi.list(undefined, { signal }), []);

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
      ...(state ? { state } : {}),
      ...(openOnly ? { open_only: true } : {}),
    }),
    [limit, offset, filters, state, openOnly]
  );

  const { data, error, loading, refresh } = usePolling(
    ({ signal }) => eventsApi.list(params, { signal }),
    { intervalMs: autoRefresh ? 15000 : 0, deps: [JSON.stringify(params), autoRefresh] }
  );

  const cameraNames = useMemo(
    () => new Map((cameraList || []).map((camera) => [camera.id, camera.name])),
    [cameraList]
  );

  const items = data?.items || [];

  return (
    <Box>
      <PageHeader
        title="Blockage events"
        subtitle="One row per confirmed obstruction episode — opened when the temporal filter accepts it, closed when the exit is clear again."
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
        <Stack direction={{ xs: "column", md: "row" }} spacing={2} alignItems={{ md: "center" }}>

          <TextField
            select
            size="small"
            label="State"
            value={state}
            onChange={(event) => setParam({ state: event.target.value })}
            sx={{ minWidth: 160 }}
          >
            <MenuItem value="">Any state</MenuItem>
            {[BLOCKAGE_STATE.PARTIAL, BLOCKAGE_STATE.FULL, BLOCKAGE_STATE.CLEAR].map((value) => (
              <MenuItem key={value} value={value}>
                {value}
              </MenuItem>
            ))}
          </TextField>

          <FormControlLabel
            control={
              <Switch
                checked={openOnly}
                onChange={(event) => setParam({ open_only: event.target.checked })}
              />
            }
            label="Still open only"
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
                    <TableCell>Ended</TableCell>
                    <TableCell>Duration</TableCell>
                    <TableCell>State</TableCell>
                    <TableCell>Peak</TableCell>
                    <TableCell align="right">Min accessible</TableCell>
                    <TableCell align="right">Peak risk</TableCell>
                    <TableCell>Blocked by</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((event) => (
                    <TableRow key={event.id} hover>
                      <TableCell>{event.id}</TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          component={RouterLink}
                          to={`/cameras/${event.camera_id}`}
                          sx={{ textTransform: "none", p: 0, minWidth: 0 }}
                        >
                          {cameraNames.get(event.camera_id) || `Camera ${event.camera_id}`}
                        </Button>
                      </TableCell>
                      <TableCell>{formatDateTime(event.started_at)}</TableCell>
                      <TableCell>
                        {event.ended_at ? (
                          formatDateTime(event.ended_at)
                        ) : (
                          <Chip size="small" color="warning" label="open" />
                        )}
                      </TableCell>
                      <TableCell>{formatDuration(event.duration_s)}</TableCell>
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
    </Box>
  );
}
