import { useState } from "react";
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
import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import PersonAddIcon from "@mui/icons-material/PersonAdd";
import KeyIcon from "@mui/icons-material/Key";

import { errorMessage } from "../../api/client";
import { auth as authApi, workspaces as workspacesApi } from "../../api/endpoints";
import { useAsync } from "../../hooks/useAsync";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../components/Toast";
import { ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { formatDateTime } from "../../utils/format";

const PLATFORM_ROLES = [
  { value: "user", label: "user", hint: "Gets the role of each workspace membership" },
  { value: "admin", label: "admin", hint: "Workspace admin wherever they are a member" },
  { value: "superadmin", label: "superadmin", hint: "Manages users and every workspace" },
];
const WORKSPACE_ROLES = ["viewer", "member", "admin"];
const PASSWORD_HELP =
  "At least 10 characters, with three of: lowercase, uppercase, digit, symbol.";

function CreateUserDialog({ onClose, onDone }) {
  const toast = useToast();
  const { data: allWorkspaces } = useAsync((opts) =>
    workspacesApi.list({ include_inactive: false }, opts)
  );
  const [form, setForm] = useState({
    username: "",
    email: "",
    full_name: "",
    password: "",
    role: "user",
    workspace_id: "",
    workspace_role: "member",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.createUser({
        ...form,
        full_name: form.full_name || undefined,
        workspace_id: form.workspace_id === "" ? undefined : Number(form.workspace_id),
      });
      toast.success(`Created ${form.username}`);
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="sm" fullWidth>
      <Box component="form" onSubmit={submit}>
        <DialogTitle>Create user</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField label="Username" value={form.username} onChange={set("username")} required fullWidth autoFocus />
              <TextField label="Full name" value={form.full_name} onChange={set("full_name")} fullWidth />
            </Stack>
            <TextField label="Email" type="email" value={form.email} onChange={set("email")} required fullWidth />
            <TextField
              label="Password"
              type="password"
              value={form.password}
              onChange={set("password")}
              autoComplete="new-password"
              helperText={PASSWORD_HELP}
              required
              fullWidth
            />
            <TextField
              select
              label="Platform role"
              value={form.role}
              onChange={set("role")}
              helperText={PLATFORM_ROLES.find((r) => r.value === form.role)?.hint}
              fullWidth
            >
              {PLATFORM_ROLES.map((r) => (
                <MenuItem key={r.value} value={r.value}>
                  {r.label}
                </MenuItem>
              ))}
            </TextField>
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                select
                label="Workspace"
                value={form.workspace_id}
                onChange={set("workspace_id")}
                helperText="Optional — add them later from Manage workspaces"
                fullWidth
              >
                <MenuItem value="">None</MenuItem>
                {(allWorkspaces || []).map((w) => (
                  <MenuItem key={w.id} value={w.id}>
                    {w.name}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                select
                label="Workspace role"
                value={form.workspace_role}
                onChange={set("workspace_role")}
                disabled={form.workspace_id === ""}
                fullWidth
              >
                {WORKSPACE_ROLES.map((r) => (
                  <MenuItem key={r} value={r}>
                    {r}
                  </MenuItem>
                ))}
              </TextField>
            </Stack>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={busy}>
            {busy ? "Creating…" : "Create"}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}

function ResetPasswordDialog({ target, onClose }) {
  const toast = useToast();
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await authApi.updateUser(target.id, { password });
      toast.success(`Password reset for ${target.username}; they were signed out everywhere`);
      onClose();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <Box component="form" onSubmit={submit}>
        <DialogTitle>Reset password — {target.username}</DialogTitle>
        <DialogContent>
          <Stack spacing={2} sx={{ pt: 1 }}>
            {error && <Alert severity="error">{error}</Alert>}
            <TextField
              label="New password"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              helperText={PASSWORD_HELP}
              autoFocus
              required
              fullWidth
            />
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="contained" disabled={busy || !password}>
            Reset
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}

/**
 * Every account on the deployment. As on the platform, only a superadmin
 * creates accounts; there is no public signup once the first one exists.
 */
export default function AdminUsers() {
  const { user: currentUser } = useAuth();
  const toast = useToast();
  const { data: users, error, loading, refresh } = useAsync((opts) => authApi.listUsers(opts));
  const [createOpen, setCreateOpen] = useState(false);
  const [resetTarget, setResetTarget] = useState(null);

  const updateUser = async (target, changes) => {
    try {
      await authApi.updateUser(target.id, changes);
      toast.success(`Updated ${target.username}`);
      refresh();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  return (
    <Box>
      <PageHeader
        title="Users"
        subtitle="Every account on this deployment"
        actions={
          <Button variant="contained" startIcon={<PersonAddIcon />} onClick={() => setCreateOpen(true)}>
            Create user
          </Button>
        }
      />

      {error && <ErrorState error={error} onRetry={refresh} />}

      {loading && !users ? (
        <Loading label="Loading users…" />
      ) : (
        <Card>
          <CardContent sx={{ p: 0 }}>
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Username</TableCell>
                    <TableCell>Email</TableCell>
                    <TableCell>Platform role</TableCell>
                    <TableCell>Active</TableCell>
                    <TableCell>Last login</TableCell>
                    <TableCell align="right">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(users || []).map((u) => {
                    const isSelf = u.id === currentUser?.id;
                    return (
                      <TableRow key={u.id} hover>
                        <TableCell>
                          {u.username}
                          {u.full_name && (
                            <Typography variant="caption" color="text.secondary" display="block">
                              {u.full_name}
                            </Typography>
                          )}
                        </TableCell>
                        <TableCell>{u.email}</TableCell>
                        <TableCell>
                          <Tooltip title={isSelf ? "You cannot change your own role" : ""}>
                            <span>
                              <Select
                                size="small"
                                value={u.role}
                                disabled={isSelf}
                                onChange={(e) => updateUser(u, { role: e.target.value })}
                              >
                                {PLATFORM_ROLES.map((r) => (
                                  <MenuItem key={r.value} value={r.value}>
                                    {r.label}
                                  </MenuItem>
                                ))}
                              </Select>
                            </span>
                          </Tooltip>
                        </TableCell>
                        <TableCell>
                          <Tooltip title={isSelf ? "You cannot deactivate your own account" : ""}>
                            <span>
                              <Switch
                                size="small"
                                checked={u.is_active}
                                disabled={isSelf}
                                onChange={(e) => updateUser(u, { is_active: e.target.checked })}
                              />
                            </span>
                          </Tooltip>
                          {!u.is_active && <Chip size="small" color="default" label="inactive" sx={{ ml: 1 }} />}
                        </TableCell>
                        <TableCell>
                          {u.last_login_at ? formatDateTime(u.last_login_at) : "Never"}
                        </TableCell>
                        <TableCell align="right">
                          <Tooltip title="Reset password">
                            <IconButton size="small" onClick={() => setResetTarget(u)}>
                              <KeyIcon fontSize="small" />
                            </IconButton>
                          </Tooltip>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>
      )}

      {createOpen && (
        <CreateUserDialog
          onClose={() => setCreateOpen(false)}
          onDone={() => {
            setCreateOpen(false);
            refresh();
          }}
        />
      )}
      {resetTarget && <ResetPasswordDialog target={resetTarget} onClose={() => setResetTarget(null)} />}
    </Box>
  );
}
