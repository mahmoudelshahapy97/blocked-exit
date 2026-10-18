import { useEffect, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Dialog from "@mui/material/Dialog";
import DialogActions from "@mui/material/DialogActions";
import DialogContent from "@mui/material/DialogContent";
import DialogTitle from "@mui/material/DialogTitle";
import IconButton from "@mui/material/IconButton";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Tab from "@mui/material/Tab";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tabs from "@mui/material/Tabs";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import AddIcon from "@mui/icons-material/Add";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import PersonAddIcon from "@mui/icons-material/PersonAdd";

import { errorMessage } from "../../api/client";
import { auth as authApi, workspaces as workspacesApi } from "../../api/endpoints";
import { useAsync } from "../../hooks/useAsync";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../components/Toast";
import { EmptyState, ErrorState, Loading } from "../../components/DataStates";
import ConfirmDialog from "../../components/ConfirmDialog";
import PageHeader from "../../components/PageHeader";
import { formatDateTime } from "../../utils/format";

const WORKSPACE_ROLES = ["viewer", "member", "admin"];

function WorkspaceDialog({ onClose, onDone }) {
  const toast = useToast();
  const [form, setForm] = useState({ name: "", description: "", camera_quota: 25 });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const created = await workspacesApi.create({
        name: form.name.trim(),
        description: form.description || undefined,
        camera_quota: Number(form.camera_quota),
      });
      toast.success(`Created ${created.name}`);
      onDone(created);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <Box component="form" onSubmit={submit}>
        <DialogTitle>Add workspace</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label="Name" value={form.name} onChange={set("name")} required autoFocus fullWidth />
            <TextField
              label="Description"
              value={form.description}
              onChange={set("description")}
              multiline
              minRows={2}
              fullWidth
            />
            <TextField
              label="Camera quota"
              type="number"
              value={form.camera_quota}
              onChange={set("camera_quota")}
              inputProps={{ min: 1, max: 10000 }}
              required
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={busy || !form.name.trim()}>
            Create
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}

function AddMemberDialog({ workspace, existingUserIds, onClose, onDone }) {
  const toast = useToast();
  const { data: users } = useAsync((opts) => authApi.listUsers(opts));
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("member");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const candidates = (users || []).filter((u) => !existingUserIds.has(u.id));

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const member = await workspacesApi.addMember(workspace.id, { user_id: Number(userId), role });
      toast.success(`Added ${member.username} as ${role}`);
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Add member to {workspace.name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            select
            label="User"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            helperText={
              users && !candidates.length
                ? "Everyone is already a member. Create accounts under Users."
                : "Accounts are created under Users"
            }
            fullWidth
          >
            {candidates.map((u) => (
              <MenuItem key={u.id} value={u.id}>
                {u.username} — {u.email}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label="Role" value={role} onChange={(e) => setRole(e.target.value)} fullWidth>
            {WORKSPACE_ROLES.map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={submit} disabled={busy || userId === ""}>
          Add
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function MembersTab({ workspace }) {
  const toast = useToast();
  const { refreshProfile } = useAuth();
  const { data: members, error, loading, refresh } = useAsync(
    (opts) => workspacesApi.members(workspace.id, opts),
    [workspace.id]
  );
  const [addOpen, setAddOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState(null);

  const changeRole = async (member, role) => {
    try {
      await workspacesApi.updateMember(workspace.id, member.id, role);
      toast.success(`${member.username} is now ${role}`);
      refresh();
      refreshProfile();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const remove = async () => {
    try {
      await workspacesApi.removeMember(workspace.id, removeTarget.id);
      toast.success(`Removed ${removeTarget.username}`);
      refresh();
      refreshProfile();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setRemoveTarget(null);
    }
  };

  return (
    <Box>
      <Stack direction="row" justifyContent="flex-end" sx={{ mb: 2 }}>
        <Button variant="contained" startIcon={<PersonAddIcon />} onClick={() => setAddOpen(true)}>
          Add member
        </Button>
      </Stack>
      {error && <ErrorState error={error} onRetry={refresh} />}
      {loading && !members ? (
        <Loading label="Loading members…" />
      ) : (
        <Card>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Username</TableCell>
                  <TableCell>Email</TableCell>
                  <TableCell>Role</TableCell>
                  <TableCell align="right">Actions</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(members || []).map((m) => (
                  <TableRow key={m.id} hover>
                    <TableCell>{m.username}</TableCell>
                    <TableCell>{m.email}</TableCell>
                    <TableCell>
                      <Select size="small" value={m.role} onChange={(e) => changeRole(m, e.target.value)}>
                        {WORKSPACE_ROLES.map((r) => (
                          <MenuItem key={r} value={r}>
                            {r}
                          </MenuItem>
                        ))}
                      </Select>
                    </TableCell>
                    <TableCell align="right">
                      <Tooltip title="Remove from workspace">
                        <IconButton size="small" color="error" onClick={() => setRemoveTarget(m)}>
                          <DeleteOutlineIcon fontSize="small" />
                        </IconButton>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}
      {addOpen && (
        <AddMemberDialog
          workspace={workspace}
          existingUserIds={new Set((members || []).map((m) => m.user_id))}
          onClose={() => setAddOpen(false)}
          onDone={() => {
            setAddOpen(false);
            refresh();
          }}
        />
      )}
      <ConfirmDialog
        open={Boolean(removeTarget)}
        title="Remove member"
        description={removeTarget ? `Remove ${removeTarget.username} from ${workspace.name}?` : ""}
        confirmLabel="Remove"
        confirmColor="error"
        onConfirm={remove}
        onClose={() => setRemoveTarget(null)}
      />
    </Box>
  );
}

function SettingsTab({ workspace, onSaved }) {
  const toast = useToast();
  const [form, setForm] = useState({
    name: workspace.name,
    description: workspace.description || "",
    camera_quota: workspace.camera_quota,
  });
  const [busy, setBusy] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const save = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      await workspacesApi.update(workspace.id, {
        name: form.name.trim(),
        description: form.description,
        camera_quota: Number(form.camera_quota),
      });
      toast.success("Workspace saved");
      onSaved();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card component="form" onSubmit={save} sx={{ maxWidth: 560 }}>
      <CardContent>
        <Stack spacing={2}>
          <TextField label="Name" value={form.name} onChange={set("name")} required fullWidth />
          <TextField
            label="Description"
            value={form.description}
            onChange={set("description")}
            multiline
            minRows={2}
            fullWidth
          />
          <TextField
            label="Camera quota"
            type="number"
            value={form.camera_quota}
            onChange={set("camera_quota")}
            inputProps={{ min: 1, max: 10000 }}
            helperText={`${workspace.camera_count} in use`}
            fullWidth
          />
          <Box>
            <Button type="submit" variant="contained" disabled={busy}>
              Save
            </Button>
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}

function CamerasTab({ workspace }) {
  const { data: cameras, error, loading, refresh } = useAsync(
    (opts) => workspacesApi.cameras(workspace.id, opts),
    [workspace.id]
  );
  if (error) return <ErrorState error={error} onRetry={refresh} />;
  if (loading && !cameras) return <Loading label="Loading cameras…" />;
  if (!cameras?.length) {
    return (
      <EmptyState
        title="No cameras"
        description="Switch into this workspace to add exits."
      />
    );
  }
  return (
    <Card>
      <TableContainer>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>Location</TableCell>
              <TableCell>Source</TableCell>
              <TableCell>Strategy</TableCell>
              <TableCell>Status</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {cameras.map((c) => (
              <TableRow key={c.id} hover>
                <TableCell>{c.name}</TableCell>
                <TableCell>{c.location || "—"}</TableCell>
                <TableCell sx={{ fontFamily: "monospace", fontSize: 12, wordBreak: "break-all" }}>
                  {c.source}
                </TableCell>
                <TableCell>{c.strategy}</TableCell>
                <TableCell>
                  <Chip
                    size="small"
                    label={c.enabled ? "enabled" : "disabled"}
                    color={c.enabled ? "success" : "default"}
                    variant="outlined"
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Card>
  );
}

function WorkspaceDetail({ workspaceId }) {
  const navigate = useNavigate();
  const toast = useToast();
  const { activeWorkspaceId, switchWorkspace, refreshProfile } = useAuth();
  const [tab, setTab] = useState("members");
  const [confirm, setConfirm] = useState(null); // "deactivate" | "delete"
  const { data: workspace, error, loading, refresh } = useAsync(
    (opts) => workspacesApi.get(workspaceId, opts),
    [workspaceId]
  );

  if (error) return <ErrorState error={error} onRetry={refresh} />;
  if (loading && !workspace) return <Loading label="Loading workspace…" />;

  const run = async (action, message) => {
    try {
      await action();
      toast.success(message);
      await refreshProfile();
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setConfirm(null);
    }
  };

  const deactivate = () =>
    run(async () => {
      await workspacesApi.deactivate(workspace.id);
      refresh();
    }, `${workspace.name} deactivated; its cameras were stopped`);
  const reactivate = () =>
    run(async () => {
      await workspacesApi.update(workspace.id, { is_active: true });
      refresh();
    }, `${workspace.name} reactivated`);
  const remove = () =>
    run(async () => {
      await workspacesApi.remove(workspace.id);
      navigate("/admin/workspaces", { replace: true });
    }, `${workspace.name} deleted`);

  return (
    <Box>
      <Button component={RouterLink} to="/admin/workspaces" startIcon={<ArrowBackIcon />} sx={{ mb: 1 }}>
        All workspaces
      </Button>
      <PageHeader
        title={workspace.name}
        subtitle={
          `${workspace.camera_count}/${workspace.camera_quota} cameras · created ` +
          formatDateTime(workspace.created_at)
        }
        actions={
          <>
            {workspace.is_active && workspace.id !== activeWorkspaceId && (
              <Button
                variant="outlined"
                onClick={() =>
                  switchWorkspace(workspace.id).then(
                    () => toast.success(`Switched to ${workspace.name}`),
                    (err) => toast.error(errorMessage(err))
                  )
                }
              >
                Switch to it
              </Button>
            )}
            {workspace.is_active ? (
              <Button color="warning" variant="outlined" onClick={() => setConfirm("deactivate")}>
                Deactivate
              </Button>
            ) : (
              <>
                <Button variant="outlined" onClick={reactivate}>
                  Reactivate
                </Button>
                <Button color="error" variant="contained" onClick={() => setConfirm("delete")}>
                  Delete
                </Button>
              </>
            )}
          </>
        }
      />
      {!workspace.is_active && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          Deactivated: nobody can work in this workspace and its cameras are stopped.
        </Alert>
      )}

      <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ mb: 2 }}>
        <Tab value="members" label="Members" />
        <Tab value="settings" label="Settings" />
        <Tab value="cameras" label="Cameras" />
      </Tabs>
      {tab === "members" && <MembersTab workspace={workspace} />}
      {tab === "settings" && <SettingsTab key={workspace.id} workspace={workspace} onSaved={refresh} />}
      {tab === "cameras" && <CamerasTab workspace={workspace} />}

      <ConfirmDialog
        open={confirm === "deactivate"}
        title="Deactivate workspace"
        description={`Stop every camera in ${workspace.name} and lock its members out until it is reactivated?`}
        confirmLabel="Deactivate"
        confirmColor="warning"
        onConfirm={deactivate}
        onClose={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "delete"}
        title="Delete workspace"
        description={`Permanently delete ${workspace.name} with all of its cameras, events and alerts? This cannot be undone.`}
        confirmLabel="Delete"
        confirmColor="error"
        onConfirm={remove}
        onClose={() => setConfirm(null)}
      />
    </Box>
  );
}

function WorkspaceList() {
  const navigate = useNavigate();
  const { refreshProfile } = useAuth();
  const [createOpen, setCreateOpen] = useState(false);
  const { data: workspaces, error, loading, refresh } = useAsync((opts) =>
    workspacesApi.list({ include_inactive: true }, opts)
  );

  return (
    <Box>
      <PageHeader
        title="Workspaces"
        subtitle="Every tenant on this deployment"
        actions={
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
            Add workspace
          </Button>
        }
      />
      {error && <ErrorState error={error} onRetry={refresh} />}
      {loading && !workspaces ? (
        <Loading label="Loading workspaces…" />
      ) : (
        <Card>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>Name</TableCell>
                  <TableCell>Cameras</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Created</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(workspaces || []).map((w) => (
                  <TableRow
                    key={w.id}
                    hover
                    onClick={() => navigate(`/admin/workspaces/${w.id}`)}
                    sx={{ cursor: "pointer" }}
                  >
                    <TableCell>
                      <Typography sx={{ fontWeight: 600 }}>{w.name}</Typography>
                      {w.description && (
                        <Typography variant="caption" color="text.secondary">
                          {w.description}
                        </Typography>
                      )}
                    </TableCell>
                    <TableCell>
                      {w.camera_count} / {w.camera_quota}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={w.is_active ? "active" : "deactivated"}
                        color={w.is_active ? "success" : "warning"}
                        variant="outlined"
                      />
                    </TableCell>
                    <TableCell>{formatDateTime(w.created_at)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}
      {createOpen && (
        <WorkspaceDialog
          onClose={() => setCreateOpen(false)}
          onDone={(created) => {
            setCreateOpen(false);
            refreshProfile();
            navigate(`/admin/workspaces/${created.id}`);
          }}
        />
      )}
    </Box>
  );
}

/** Superadmin tenancy management: the platform's Workspace page. */
export default function AdminWorkspaces() {
  const { workspaceId } = useParams();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [workspaceId]);
  return workspaceId ? <WorkspaceDetail workspaceId={Number(workspaceId)} /> : <WorkspaceList />;
}

