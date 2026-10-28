import { Link as RouterLink } from "react-router-dom";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Grid from "@mui/material/Grid2";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Typography from "@mui/material/Typography";
import ManageAccountsIcon from "@mui/icons-material/ManageAccounts";

import { workspaces as workspacesApi } from "../../api/endpoints";
import { useAsync } from "../../hooks/useAsync";
import { useAuth } from "../../context/AuthContext";
import { ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import StatCard from "../../components/StatCard";
import { useTranslation } from "react-i18next";
import i18n from "i18next";

const ROLE_COLOR = { admin: "primary", member: "info", viewer: "default" };

const ROLE_ABILITIES = {
  get viewer() { return i18n.t("workspace.abilityViewer"); },
  get member() { return i18n.t("workspace.abilityMember"); },
  get admin() { return i18n.t("workspace.abilityAdmin"); },
};

/**
 * The active workspace, read-only. As on the platform, rosters are managed by
 * a superadmin (Manage workspaces), not by workspace admins.
 */
export default function WorkspaceSettings() {
  const { t } = useTranslation();
  const { activeWorkspaceId, workspaceRole, isSuperadmin } = useAuth();

  const {
    data: workspace,
    error: workspaceError,
    refresh: refreshWorkspace,
  } = useAsync((opts) => workspacesApi.active(opts), [activeWorkspaceId]);
  const {
    data: members,
    error: membersError,
    loading: membersLoading,
    refresh: refreshMembers,
  } = useAsync(
    (opts) => workspacesApi.members(activeWorkspaceId, opts),
    [activeWorkspaceId],
    { enabled: Boolean(activeWorkspaceId) }
  );

  return (
    <Box>
      <PageHeader
        title={workspace?.name ?? t("workspace.workspace")}
        subtitle={workspace?.description || t("workspace.yourActiveWorkspace")}
        actions={
          isSuperadmin && (
            <Button
              component={RouterLink}
              to={`/admin/workspaces/${activeWorkspaceId}`}
              variant="contained"
              startIcon={<ManageAccountsIcon />}
            >
              {t("workspace.manage")}
            </Button>
          )
        }
      />

      {workspaceError && <ErrorState error={workspaceError} onRetry={refreshWorkspace} />}
      {membersError && <ErrorState error={membersError} onRetry={refreshMembers} />}

      <Grid container spacing={2} sx={{ mb: 3 }}>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatCard
            label={t("workspace.yourRole")}
            value={workspaceRole ?? "—"}
            hint={ROLE_ABILITIES[workspaceRole]}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatCard
            label={t("workspace.exits")}
            value={workspace ? `${workspace.camera_count} / ${workspace.camera_quota}` : "—"}
            hint={t("workspace.camerasUsedOfThisWorkspace")}
          />
        </Grid>
        <Grid size={{ xs: 12, sm: 4 }}>
          <StatCard label={t("workspace.members")} value={members ? members.length : "—"} />
        </Grid>
      </Grid>

      {membersLoading && !members ? (
        <Loading label={t("workspace.loadingMembers")} />
      ) : (
        <Card>
          <CardContent sx={{ p: 0 }}>
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableCell>{t("workspace.member")}</TableCell>
                    <TableCell>{t("workspace.email")}</TableCell>
                    <TableCell>{t("workspace.role")}</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {(members || []).map((member) => (
                    <TableRow key={member.id} hover>
                      <TableCell>
                        {member.username}
                        {member.full_name && (
                          <Typography variant="caption" color="text.secondary" display="block">
                            {member.full_name}
                          </Typography>
                        )}
                      </TableCell>
                      <TableCell>{member.email}</TableCell>
                      <TableCell>
                        <Chip size="small" color={ROLE_COLOR[member.role]} label={member.role} />
                        {!member.is_active && (
                          <Chip size="small" label={t("workspace.inactive")} sx={{ ml: 1 }} />
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </CardContent>
        </Card>
      )}
    </Box>
  );
}
