import { useCallback, useMemo, useState } from "react";
import { Link as RouterLink, useNavigate } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import IconButton from "@mui/material/IconButton";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";

import AddIcon from "@mui/icons-material/Add";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import StopIcon from "@mui/icons-material/Stop";
import RestartAltIcon from "@mui/icons-material/RestartAlt";
import CropFreeIcon from "@mui/icons-material/CropFree";
import EditIcon from "@mui/icons-material/Edit";
import DeleteIcon from "@mui/icons-material/DeleteOutline";

import { errorMessage } from "../../api/client";
import { cameras as camerasApi, monitoring } from "../../api/endpoints";
import { usePolling } from "../../hooks/usePolling";
import { useMonitoringActions } from "../../hooks/useMonitoringActions";
import { useToast } from "../../components/Toast";
import { EmptyState, ErrorState, Loading } from "../../components/DataStates";
import ConfirmDialog from "../../components/ConfirmDialog";
import { RoleGate } from "../../components/ProtectedRoute";
import PageHeader from "../../components/PageHeader";
import { StateChip, StrategyChip, WorkerChip } from "../../components/StatusChips";
import { formatPct, redactUrl } from "../../utils/format";

export default function CameraList() {
  const navigate = useNavigate();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [menu, setMenu] = useState({ anchor: null, camera: null });
  const [pendingDelete, setPendingDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const {
    data: cameraList,
    error,
    loading,
    refresh,
  } = usePolling(({ signal }) => camerasApi.list(undefined, { signal }), {
    intervalMs: 15000,
  });

  // Live verdicts live on a different route from the camera records; joining
  // them here is what lets one table answer both "what is configured" and
  // "what is happening right now".
  const { data: statuses, refresh: refreshStatuses } = usePolling(
    ({ signal }) => monitoring.statusAll({ signal }),
    { intervalMs: 5000 }
  );

  const statusById = useMemo(
    () => new Map((statuses || []).map((s) => [s.camera_id, s])),
    [statuses]
  );

  const refreshAll = useCallback(async () => {
    await Promise.all([refresh(), refreshStatuses()]);
  }, [refresh, refreshStatuses]);

  const { busyId, start, stop, restart } = useMonitoringActions(refreshAll);

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return cameraList || [];
    return (cameraList || []).filter((camera) =>
      [camera.name, camera.location, camera.rtsp_url]
        .filter(Boolean)
        .some((value) => value.toLowerCase().includes(needle))
    );
  }, [cameraList, search]);

  const closeMenu = () => setMenu({ anchor: null, camera: null });

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await camerasApi.remove(pendingDelete.id);
      toast.success(`Deleted ${pendingDelete.name}`);
      setPendingDelete(null);
      await refreshAll();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setDeleting(false);
    }
  };

  return (
    <Box>
      <PageHeader
        title="Exits"
        subtitle="Registered cameras, their exit region, and what each worker is doing."
        actions={
          <>
            <TextField
              size="small"
              placeholder="Search name, location, URL…"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              sx={{ minWidth: 240 }}
            />
            <RoleGate minimum="operator">
              <Button
                variant="contained"
                startIcon={<AddIcon />}
                component={RouterLink}
                to="/cameras/new"
              >
                Add exit
              </Button>
            </RoleGate>
          </>
        }
      />

      <ErrorState error={error} onRetry={refreshAll} title="Could not load cameras" />

      <Card>
        {loading && !cameraList ? (
          <Loading label="Loading cameras…" />
        ) : filtered.length === 0 ? (
          <EmptyState
            title={search ? "No exit matches that search" : "No exits registered yet"}
            description={
              search
                ? "Try a different name, location or URL fragment."
                : "Add a camera to start monitoring an emergency exit."
            }
            action={
              !search && (
                <RoleGate minimum="operator">
                  <Button variant="contained" component={RouterLink} to="/cameras/new">
                    Add exit
                  </Button>
                </RoleGate>
              )
            }
          />
        ) : (
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Exit</TableCell>
                  <TableCell>Source</TableCell>
                  <TableCell>Strategy</TableCell>
                  <TableCell>Region</TableCell>
                  <TableCell>Worker</TableCell>
                  <TableCell>State</TableCell>
                  <TableCell align="right">Accessible</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filtered.map((camera) => {
                  const status = statusById.get(camera.id);
                  const running = Boolean(status);
                  const points = camera.door_polygon?.length || 0;
                  return (
                    <TableRow
                      key={camera.id}
                      hover
                      sx={{ cursor: "pointer" }}
                      onClick={() => navigate(`/cameras/${camera.id}`)}
                    >
                      <TableCell>
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {camera.name}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {camera.location || "—"}
                        </Typography>
                      </TableCell>
                      <TableCell sx={{ maxWidth: 260 }}>
                        <Tooltip title={redactUrl(camera.rtsp_url)}>
                          <Typography variant="caption" noWrap display="block" color="text.secondary">
                            {redactUrl(camera.rtsp_url)}
                          </Typography>
                        </Tooltip>
                        {!camera.enabled && (
                          <Typography variant="caption" color="warning.main">
                            disabled
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <StrategyChip strategy={camera.strategy} />
                      </TableCell>
                      <TableCell>
                        {points >= 3 ? (
                          <Typography variant="caption" color="success.main">
                            {points} points
                          </Typography>
                        ) : (
                          <Typography variant="caption" color="warning.main">
                            not drawn
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>
                        <WorkerChip state={status?.worker_state || "stopped"} />
                      </TableCell>
                      <TableCell>
                        <StateChip state={status?.state || "UNKNOWN"} />
                      </TableCell>
                      <TableCell align="right">
                        {status ? formatPct(status.accessibility_pct) : "—"}
                      </TableCell>
                      <TableCell align="right" onClick={(event) => event.stopPropagation()}>
                        <RoleGate minimum="operator">
                          <Stack direction="row" spacing={0.5} justifyContent="flex-end">
                            {running ? (
                              <Tooltip title="Stop monitoring">
                                <span>
                                  <IconButton
                                    size="small"
                                    disabled={busyId === camera.id}
                                    onClick={() => stop(camera.id)}
                                  >
                                    <StopIcon fontSize="small" />
                                  </IconButton>
                                </span>
                              </Tooltip>
                            ) : (
                              <Tooltip title="Start monitoring">
                                <span>
                                  <IconButton
                                    size="small"
                                    color="primary"
                                    disabled={busyId === camera.id}
                                    onClick={() => start(camera.id)}
                                  >
                                    <PlayArrowIcon fontSize="small" />
                                  </IconButton>
                                </span>
                              </Tooltip>
                            )}
                            <IconButton
                              size="small"
                              onClick={(event) =>
                                setMenu({ anchor: event.currentTarget, camera })
                              }
                            >
                              <MoreVertIcon fontSize="small" />
                            </IconButton>
                          </Stack>
                        </RoleGate>
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          </TableContainer>
        )}
      </Card>

      <Menu anchorEl={menu.anchor} open={Boolean(menu.anchor)} onClose={closeMenu}>
        <MenuItem
          onClick={() => {
            navigate(`/cameras/${menu.camera.id}/zone`);
            closeMenu();
          }}
        >
          <CropFreeIcon fontSize="small" sx={{ mr: 1.5 }} />
          Draw exit region
        </MenuItem>
        <MenuItem
          onClick={() => {
            navigate(`/cameras/${menu.camera.id}/edit`);
            closeMenu();
          }}
        >
          <EditIcon fontSize="small" sx={{ mr: 1.5 }} />
          Edit settings
        </MenuItem>
        <MenuItem
          onClick={() => {
            restart(menu.camera.id);
            closeMenu();
          }}
        >
          <RestartAltIcon fontSize="small" sx={{ mr: 1.5 }} />
          Restart worker
        </MenuItem>
        <MenuItem
          onClick={() => {
            setPendingDelete(menu.camera);
            closeMenu();
          }}
          sx={{ color: "error.main" }}
        >
          <DeleteIcon fontSize="small" sx={{ mr: 1.5 }} />
          Delete
        </MenuItem>
      </Menu>

      <ConfirmDialog
        open={Boolean(pendingDelete)}
        title={`Delete ${pendingDelete?.name}?`}
        // The FK cascade is real and worth spelling out — an operator deleting
        // a camera to "clean up" would otherwise lose its incident history.
        description="This stops its worker and permanently removes the camera together with every blockage event and alert recorded for it."
        confirmLabel="Delete"
        confirmColor="error"
        busy={deleting}
        onConfirm={handleDelete}
        onClose={() => setPendingDelete(null)}
      />
    </Box>
  );
}
