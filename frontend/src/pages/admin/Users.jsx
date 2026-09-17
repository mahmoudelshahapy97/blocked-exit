import Box from "@mui/material/Box";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import MenuItem from "@mui/material/MenuItem";
import Select from "@mui/material/Select";
import Switch from "@mui/material/Switch";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Tooltip from "@mui/material/Tooltip";

import { errorMessage } from "../../api/client";
import { auth as authApi } from "../../api/endpoints";
import { useAsync } from "../../hooks/useAsync";
import { useAuth } from "../../context/AuthContext";
import { useToast } from "../../components/Toast";
import { ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { formatDateTime } from "../../utils/format";

const ROLES = ["user", "admin"];

/**
 * Every account on the deployment, not scoped to any one workspace. Distinct
 * from workspace membership (see settings/Workspace.jsx) -- this is the
 * platform-wide role that grants access to pages like this one.
 */
export default function AdminUsers() {
  const { user: currentUser } = useAuth();
  const toast = useToast();
  const { data: users, error, loading, refresh } = useAsync((opts) => authApi.listUsers(opts));

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
      <PageHeader title="Users" subtitle="Every account on this deployment" />

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
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(users || []).map((u) => {
                    const isSelf = u.id === currentUser?.id;
                    return (
                      <TableRow key={u.id} hover>
                        <TableCell>{u.username}</TableCell>
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
                                {ROLES.map((r) => (
                                  <MenuItem key={r} value={r}>
                                    {r}
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
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
