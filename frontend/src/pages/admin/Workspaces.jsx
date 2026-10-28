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
import { useTranslation } from "react-i18next";

const WORKSPACE_ROLES = ["viewer", "member", "admin"];

function WorkspaceDialog({ onClose, onDone }) {
  const { t } = useTranslation();
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
      toast.success(t("workspaces.createdName", { name: created.name }));
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
        <DialogTitle>{t("workspaces.addWorkspace")}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField label={t("workspaces.name")} value={form.name} onChange={set("name")} required autoFocus fullWidth />
            <TextField
              label={t("workspaces.description")}
              value={form.description}
              onChange={set("description")}
              multiline
              minRows={2}
              fullWidth
            />
            <TextField
              label={t("workspaces.cameraQuota")}
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
          <Button onClick={onClose}>{t("workspaces.cancel")}</Button>
          <Button type="submit" variant="contained" disabled={busy || !form.name.trim()}>
            {t("workspaces.create")}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}

function AddMemberDialog({ workspace, existingUserIds, onClose, onDone }) {
  const { t } = useTranslation();
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
      toast.success(t("workspaces.addedUsernameAsRole", { username: member.username, role }));
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>{t("workspaces.addMemberToName", { name: workspace.name })}</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <TextField
            select
            label={t("workspaces.user")}
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            helperText={
              users && !candidates.length
                ? t("workspaces.everyoneIsAlreadyAMember")
                : t("workspaces.accountsAreCreatedUnderUsers")
            }
            fullWidth
          >
            {candidates.map((u) => (
              <MenuItem key={u.id} value={u.id}>
                {u.username} — {u.email}
              </MenuItem>
            ))}
          </TextField>
          <TextField select label={t("workspaces.role")} value={role} onChange={(e) => setRole(e.target.value)} fullWidth>
            {WORKSPACE_ROLES.map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>{t("workspaces.cancel")}</Button>
        <Button variant="contained" onClick={submit} disabled={busy || userId === ""}>
          {t("workspaces.add")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

function MembersTab({ workspace }) {
  const { t } = useTranslation();
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
      toast.success(t("workspaces.usernameIsNowRole", { username: member.username, role }));
      refresh();
      refreshProfile();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const remove = async () => {
    try {
      await workspacesApi.removeMember(workspace.id, removeTarget.id);
      toast.success(t("workspaces.removedUsername", { username: removeTarget.username }));
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
          {t("workspaces.addMember")}
        </Button>
      </Stack>
      {error && <ErrorState error={error} onRetry={refresh} />}
      {loading && !members ? (
        <Loading label={t("workspaces.loadingMembers")} />
      ) : (
        <Card>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>{t("workspaces.username")}</TableCell>
                  <TableCell>{t("workspaces.email")}</TableCell>
                  <TableCell>{t("workspaces.role")}</TableCell>
                  <TableCell align="right">{t("workspaces.actions")}</TableCell>
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
                      <Tooltip title={t("workspaces.removeFromWorkspace")}>
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
        title={t("workspaces.removeMember")}
        description={removeTarget ? t("workspaces.removeUsernameFromName", { username: removeTarget.username, name: workspace.name }) : ""}
        confirmLabel={t("workspaces.remove")}
        confirmColor="error"
        onConfirm={remove}
        onClose={() => setRemoveTarget(null)}
      />
    </Box>
  );
}

function SettingsTab({ workspace, onSaved }) {
  const { t } = useTranslation();
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
      toast.success(t("workspaces.workspaceSaved"));
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
          <TextField label={t("workspaces.name")} value={form.name} onChange={set("name")} required fullWidth />
          <TextField
            label={t("workspaces.description")}
            value={form.description}
            onChange={set("description")}
            multiline
            minRows={2}
            fullWidth
          />
          <TextField
            label={t("workspaces.cameraQuota")}
            type="number"
            value={form.camera_quota}
            onChange={set("camera_quota")}
            inputProps={{ min: 1, max: 10000 }}
            helperText={t("workspaces.cameraCountInUse", { camera_count: workspace.camera_count })}
            fullWidth
          />
          <Box>
            <Button type="submit" variant="contained" disabled={busy}>
              {t("workspaces.save")}
            </Button>
          </Box>
        </Stack>
      </CardContent>
    </Card>
  );
}

function CamerasTab({ workspace }) {
  const { t } = useTranslation();
  const { data: cameras, error, loading, refresh } = useAsync(
    (opts) => workspacesApi.cameras(workspace.id, opts),
    [workspace.id]
  );
  if (error) return <ErrorState error={error} onRetry={refresh} />;
  if (loading && !cameras) return <Loading label={t("workspaces.loadingCameras")} />;
  if (!cameras?.length) {
    return (
      <EmptyState
        title={t("workspaces.noCameras")}
        description={t("workspaces.switchIntoThisWorkspaceTo")}
      />
    );
  }
  return (
    <Card>
      <TableContainer>
        <Table>
          <TableHead>
            <TableRow>
              <TableCell>{t("workspaces.name")}</TableCell>
              <TableCell>{t("workspaces.location")}</TableCell>
              <TableCell>{t("workspaces.source")}</TableCell>
              <TableCell>{t("workspaces.strategy")}</TableCell>
              <TableCell>{t("workspaces.status")}</TableCell>
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
                    label={c.enabled ? t("workspaces.enabled") : t("workspaces.disabled")}
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
  const { t } = useTranslation();
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
  if (loading && !workspace) return <Loading label={t("workspaces.loadingWorkspace")} />;

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
        {t("workspaces.allWorkspaces")}
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
                    () => toast.success(t("workspaces.switchedToName", { name: workspace.name })),
                    (err) => toast.error(errorMessage(err))
                  )
                }
              >
                {t("workspaces.switchToIt")}
              </Button>
            )}
            {workspace.is_active ? (
              <Button color="warning" variant="outlined" onClick={() => setConfirm("deactivate")}>
                {t("workspaces.deactivate")}
              </Button>
            ) : (
              <>
                <Button variant="outlined" onClick={reactivate}>
                  {t("workspaces.reactivate")}
                </Button>
                <Button color="error" variant="contained" onClick={() => setConfirm("delete")}>
                  {t("workspaces.delete")}
                </Button>
              </>
            )}
          </>
        }
      />
      {!workspace.is_active && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {t("workspaces.deactivatedNobodyCanWorkIn")}
        </Alert>
      )}

      <Tabs value={tab} onChange={(_, value) => setTab(value)} sx={{ mb: 2 }}>
        <Tab value="members" label={t("workspaces.members")} />
        <Tab value="settings" label={t("workspaces.settings")} />
        <Tab value="cameras" label={t("workspaces.cameras")} />
      </Tabs>
      {tab === "members" && <MembersTab workspace={workspace} />}
      {tab === "settings" && <SettingsTab key={workspace.id} workspace={workspace} onSaved={refresh} />}
      {tab === "cameras" && <CamerasTab workspace={workspace} />}

      <ConfirmDialog
        open={confirm === "deactivate"}
        title={t("workspaces.deactivateWorkspace")}
        description={t("workspaces.stopEveryCameraInName", { name: workspace.name })}
        confirmLabel={t("workspaces.deactivate")}
        confirmColor="warning"
        onConfirm={deactivate}
        onClose={() => setConfirm(null)}
      />
      <ConfirmDialog
        open={confirm === "delete"}
        title={t("workspaces.deleteWorkspace")}
        description={t("workspaces.permanentlyDeleteNameWithAll", { name: workspace.name })}
        confirmLabel={t("workspaces.delete")}
        confirmColor="error"
        onConfirm={remove}
        onClose={() => setConfirm(null)}
      />
    </Box>
  );
}

function WorkspaceList() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { refreshProfile } = useAuth();
  const [createOpen, setCreateOpen] = useState(false);
  const { data: workspaces, error, loading, refresh } = useAsync((opts) =>
    workspacesApi.list({ include_inactive: true }, opts)
  );

  return (
    <Box>
      <PageHeader
        title={t("workspaces.workspaces")}
        subtitle={t("workspaces.everyTenantOnThisDeployment")}
        actions={
          <Button variant="contained" startIcon={<AddIcon />} onClick={() => setCreateOpen(true)}>
            {t("workspaces.addWorkspace")}
          </Button>
        }
      />
      {error && <ErrorState error={error} onRetry={refresh} />}
      {loading && !workspaces ? (
        <Loading label={t("workspaces.loadingWorkspaces")} />
      ) : (
        <Card>
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell>{t("workspaces.name")}</TableCell>
                  <TableCell>{t("workspaces.cameras")}</TableCell>
                  <TableCell>{t("workspaces.status")}</TableCell>
                  <TableCell>{t("workspaces.created")}</TableCell>
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
                        label={w.is_active ? t("workspaces.active") : t("workspaces.deactivated")}
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

