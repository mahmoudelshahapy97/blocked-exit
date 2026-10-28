import { AppShell, NotificationBell, NotificationsProvider, usePolling } from "@insighteye/ui";
import { useTranslation } from "react-i18next";
import DashboardIcon from "@mui/icons-material/SpaceDashboard";
import VideocamIcon from "@mui/icons-material/Videocam";
import GridViewIcon from "@mui/icons-material/GridView";
import HistoryIcon from "@mui/icons-material/History";
import NotificationsActiveIcon from "@mui/icons-material/NotificationsActive";
import NotificationsIcon from "@mui/icons-material/Notifications";
import InsightsIcon from "@mui/icons-material/Insights";
import SettingsIcon from "@mui/icons-material/Settings";
import GroupIcon from "@mui/icons-material/Group";
import WorkspacesIcon from "@mui/icons-material/Workspaces";
import ManageSearchIcon from "@mui/icons-material/ManageSearch";
import DoorFrontIcon from "@mui/icons-material/DoorFront";

import { events } from "../api/endpoints";
import { useAuth } from "../context/AuthContext";

/** Blockages still going on in the active workspace, for the Events entry. */
function useOpenBlockages(workspaceId) {
  const overview = usePolling(({ signal }) => events.overview({ signal }), {
    intervalMs: 10000,
    enabled: Boolean(workspaceId),
    deps: [workspaceId],
  });
  return overview.data?.open_events ?? 0;
}

/**
 * Watch the exits, triage what they raise, then the workspace and platform
 * admin. `perm` is the role floor the API enforces for the same action
 * (viewer < operator = member < admin; superadmin for the platform pages).
 */
export function AppLayout() {
  const { t } = useTranslation();
  const { activeWorkspaceId } = useAuth();
  const openBlockages = useOpenBlockages(activeWorkspaceId);

  const navSections = [
    {
      heading: t("shell.monitor"),
      items: [
        { to: "/", label: t("nav.dashboard"), icon: <DashboardIcon />, end: true },
        { to: "/cameras", label: t("layout.exits"), icon: <VideocamIcon /> },
        { to: "/live", label: t("nav.liveWall"), icon: <GridViewIcon /> },
        { to: "/events", label: t("nav.events"), icon: <HistoryIcon />, badge: "openBlockages" },
        { to: "/alerts", label: t("layout.alertDeliveries"), icon: <NotificationsActiveIcon /> },
        { to: "/notifications", label: t("nav.notifications"), icon: <NotificationsIcon /> },
        { to: "/analytics", label: t("nav.analytics"), icon: <InsightsIcon /> },
      ],
    },
    {
      heading: t("shell.system"),
      items: [
        { to: "/settings/workspace", label: t("layout.workspaceSettings"), icon: <SettingsIcon /> },
        { to: "/admin/workspaces", label: t("nav.workspaces"), icon: <WorkspacesIcon />, perm: "superadmin" },
        { to: "/admin/users", label: t("nav.users"), icon: <GroupIcon />, perm: "superadmin" },
        { to: "/audit", label: t("nav.audit"), icon: <ManageSearchIcon />, perm: "superadmin" },
      ],
    },
  ];

  return (
    <NotificationsProvider>
      <AppShell
        product={{ brand: "InsightEye", tagline: t("product.tagline"), icon: <DoorFrontIcon /> }}
        navSections={navSections}
        badges={{ openBlockages }}
        topBarExtras={<NotificationBell />}
      />
    </NotificationsProvider>
  );
}

export default AppLayout;
