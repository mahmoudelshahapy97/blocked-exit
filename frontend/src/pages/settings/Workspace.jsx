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
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import TextField from "@mui/material/TextField";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutline";
import PersonAddIcon from "@mui/icons-material/PersonAdd";

import { errorMessage } from "../../api/client";
import { workspaces as workspacesApi } from "../../api/endpoints";
import { useAsync } from "../../hooks/useAsync";
import { useAuth, roleAtLeast } from "../../context/AuthContext";
import { useToast } from "../../components/Toast";
import { ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import ConfirmDialog from "../../components/ConfirmDialog";

const ROLES = ["viewer", "operator", "admin", "owner"];
const ROLE_COLOR = { owner: "secondary", admin: "primary", operator: "info", viewer: "default" };

function AddMemberDialog({ workspaceId, onClose, onDone }) {
  const toast = useToast();
  const [identifier, setIdentifier] = useState("");
  const [role, setRole] = useState("viewer");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  const submit = async () => {
    if (!identifier.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const isEmail = identifier.includes("@");
      await workspacesApi.addMember(workspaceId, {
        [isEmail ? "email" : "username"]: identifier.trim(),
        role,
      });
      toast.success(`Added ${identifier.trim()} as ${role}`);
      onDone();
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>Add a member</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          {error && <Alert severity="error">{error}</Alert>}
          <Typography variant="body2" color="text.secondary">
            They must already have an account — this workspace does not send
            invitation emails.
          </Typography>
          <TextField
            label="Username or email"
            value={identifier}
            onChange={(e) => setIdentifier(e.target.value)}
            autoFocus
            fullWidth
          />
          <Select value={role} onChange={(e) => setRole(e.target.value)} fullWidth>
            {ROLES.map((r) => (
              <MenuItem key={r} value={r}>
                {r}
              </MenuItem>
            ))}
          </Select>
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={submit} disabled={busy || !identifier.trim()}>
          {busy ? "Adding…" : "Add"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}

export default function WorkspaceSettings() {
  const { activeWorkspaceId, workspaceRole, user } = useAuth();
  const toast = useToast();
  const [addOpen, setAddOpen] = useState(false);
  const [removeTarget, setRemoveTarget] = useState(null);

  const {
    data: workspace,
    error: workspaceError,
    loading: workspaceLoading,
    refresh: refreshWorkspace,
  } = useAsync(
    (opts) => (activeWorkspaceId ? workspacesApi.get(activeWorkspaceId, opts) : Promise.resolve(null)),
    [activeWorkspaceId]
  );

  const {
    data: members,
    error: membersError,
    loading: membersLoading,
    refresh: refreshMembers,
  } = useAsync(
    (opts) => (activeWorkspaceId ? workspacesApi.members(activeWorkspaceId, opts) : Promise.resolve([])),
    [activeWorkspaceId]
  );

  const canManage = roleAtLeast(workspaceRole, "admin");

  const changeRole = async (member, role) => {
    try {
      await workspacesApi.updateMember(activeWorkspaceId, member.id, role);
      toast.success(`${member.username} is now ${role}`);
      refreshMembers();
    } catch (err) {
      toast.error(errorMessage(err));
    }
  };

  const removeMember = async () => {
    if (!removeTarget) return;
    try {
      await workspacesApi.removeMember(activeWorkspaceId, removeTarget.id);
      toast.success(`Removed ${removeTarget.username}`);
      setRemoveTarget(null);
      refreshMembers();
    } catch (err) {
      toast.error(errorMessage(err));
      setRemoveTarget(null);
    }
  };

  if (!activeWorkspaceId) {
    return <ErrorState error="No workspace selected." />;
  }

  return (
    <Box>
      <PageHeader
        title="Workspace settings"
        subtitle={workspace ? `${workspace.name} · ${workspace.camera_count}/${workspace.camera_quota} cameras` : undefined}
        actions={
          canManage && (
            <Button startIcon={<PersonAddIcon />} variant="contained" onClick={() => setAddOpen(true)}>
              Add member
            </Button>
          )
        }
      />

      {workspaceError && <ErrorState error={workspaceError} onRetry={refreshWorkspace} />}
      {membersError && <ErrorState error={membersError} onRetry={refreshMembers} />}

      {(workspaceLoading || membersLoading) && !members ? (
        <Loading label="Loading workspace…" />
      ) : (
        <Card>
          <CardContent sx={{ p: 0 }}>
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>Member</TableCell>
                    <TableCell>Email</TableCell>
                    <TableCell>Role</TableCell>
                    <TableCell align="right">Actions</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(members || []).map((member) => {
                    const isSelf = member.user_id === user?.id;
                    return (
                      <TableRow key={member.id} hover>
                        <TableCell>{member.username}</TableCell>
                        <TableCell>{member.email}</TableCell>
                        <TableCell>
                          {canManage ? (
                            <Select
                              size="small"
                              value={member.role}
                              onChange={(e) => changeRole(member, e.target.value)}
                              disabled={isSelf}
                            >
                              {ROLES.map((r) => (
                                <MenuItem key={r} value={r}>
                                  {r}
                                </MenuItem>
                              ))}
                            </Select>
                          ) : (
                            <Chip size="small" color={ROLE_COLOR[member.role]} label={member.role} />
                          )}
                        </TableCell>
                        <TableCell align="right">
                          {canManage && (
                            <Tooltip title={isSelf ? "You cannot remove yourself" : "Remove"}>
                              <span>
                                <IconButton
                                  size="small"
                                  color="error"
                                  disabled={isSelf}
                                  onClick={() => setRemoveTarget(member)}
                                >
                                  <DeleteOutlineIcon fontSize="small" />
                                </IconButton>
                              </span>
                            </Tooltip>
                          )}
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

      {addOpen && (
        <AddMemberDialog
          workspaceId={activeWorkspaceId}
          onClose={() => setAddOpen(false)}
          onDone={() => {
            setAddOpen(false);
            refreshMembers();
          }}
        />
      )}

      <ConfirmDialog
        open={Boolean(removeTarget)}
        title="Remove member"
        description={removeTarget ? `Remove ${removeTarget.username} from this workspace?` : ""}
        confirmLabel="Remove"
        confirmColor="error"
        onConfirm={removeMember}
        onClose={() => setRemoveTarget(null)}
      />
    </Box>
  );
}
