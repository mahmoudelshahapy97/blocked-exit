import { useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import AppBar from "@mui/material/AppBar";
import Avatar from "@mui/material/Avatar";
import Box from "@mui/material/Box";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Drawer from "@mui/material/Drawer";
import IconButton from "@mui/material/IconButton";
import List from "@mui/material/List";
import ListItemButton from "@mui/material/ListItemButton";
import ListItemIcon from "@mui/material/ListItemIcon";
import ListItemText from "@mui/material/ListItemText";
import Menu from "@mui/material/Menu";
import MenuItem from "@mui/material/MenuItem";
import ListSubheader from "@mui/material/ListSubheader";
import Select from "@mui/material/Select";
import Stack from "@mui/material/Stack";
import Toolbar from "@mui/material/Toolbar";
import Tooltip from "@mui/material/Tooltip";
import Typography from "@mui/material/Typography";
import useMediaQuery from "@mui/material/useMediaQuery";
import { useTheme } from "@mui/material/styles";

import DashboardIcon from "@mui/icons-material/SpaceDashboard";
import VideocamIcon from "@mui/icons-material/Videocam";
import HistoryIcon from "@mui/icons-material/History";
import NotificationsIcon from "@mui/icons-material/NotificationsActive";
import InsightsIcon from "@mui/icons-material/Insights";
import MenuIcon from "@mui/icons-material/Menu";
import DarkModeIcon from "@mui/icons-material/DarkMode";
import LightModeIcon from "@mui/icons-material/LightMode";
import MenuBookIcon from "@mui/icons-material/MenuBook";
import LogoutIcon from "@mui/icons-material/Logout";
import SettingsIcon from "@mui/icons-material/Settings";
import AdminPanelSettingsIcon from "@mui/icons-material/AdminPanelSettings";

import { health } from "../api/endpoints";
import { usePolling } from "../hooks/usePolling";
import { useAuth } from "../context/AuthContext";

const DRAWER_WIDTH = 248;

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: <DashboardIcon />, end: true },
  { to: "/cameras", label: "Exits", icon: <VideocamIcon /> },
  { to: "/events", label: "Events", icon: <HistoryIcon /> },
  { to: "/alerts", label: "Alerts", icon: <NotificationsIcon /> },
  { to: "/analytics", label: "Analytics", icon: <InsightsIcon /> },
];

/** Which workspace this session acts in — every camera/event/alert request
 *  carries it as X-Workspace-Id. Hidden entirely when there is only one. */
function WorkspaceSwitcher() {
  const { memberships, activeWorkspaceId, switchWorkspace } = useAuth();
  if (memberships.length <= 1) return null;

  return (
    <Select
      size="small"
      value={activeWorkspaceId ?? ""}
      onChange={(e) => switchWorkspace(Number(e.target.value))}
      sx={{ minWidth: 160 }}
    >
      {memberships.map((m) => (
        <MenuItem key={m.workspace_id} value={m.workspace_id}>
          {m.workspace_name}
        </MenuItem>
      ))}
    </Select>
  );
}

function UserMenu() {
  const { user, workspaceRole, isPlatformAdmin, logout } = useAuth();
  const navigate = useNavigate();
  const [anchorEl, setAnchorEl] = useState(null);

  if (!user) return null;
  const initial = (user.full_name || user.username || "?").charAt(0).toUpperCase();

  const handleLogout = async () => {
    setAnchorEl(null);
    await logout();
    navigate("/login", { replace: true });
  };

  return (
    <>
      <Tooltip title={user.username}>
        <IconButton onClick={(e) => setAnchorEl(e.currentTarget)} size="small">
          <Avatar sx={{ width: 32, height: 32, fontSize: 14 }}>{initial}</Avatar>
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchorEl} open={Boolean(anchorEl)} onClose={() => setAnchorEl(null)}>
        <ListSubheader sx={{ lineHeight: 1.6 }}>
          {user.full_name || user.username}
          <Typography variant="caption" color="text.secondary" display="block">
            {user.email} · {workspaceRole || "no role"}
            {isPlatformAdmin && " · platform admin"}
          </Typography>
        </ListSubheader>
        <MenuItem
          component={NavLink}
          to="/settings/workspace"
          onClick={() => setAnchorEl(null)}
        >
          <ListItemIcon>
            <SettingsIcon fontSize="small" />
          </ListItemIcon>
          Workspace settings
        </MenuItem>
        {isPlatformAdmin && (
          <MenuItem component={NavLink} to="/admin/users" onClick={() => setAnchorEl(null)}>
            <ListItemIcon>
              <AdminPanelSettingsIcon fontSize="small" />
            </ListItemIcon>
            All users
          </MenuItem>
        )}
        <Divider />
        <MenuItem onClick={handleLogout}>
          <ListItemIcon>
            <LogoutIcon fontSize="small" />
          </ListItemIcon>
          Sign out
        </MenuItem>
      </Menu>
    </>
  );
}

/** Backend reachability, shown in the bar so a dead API is never a mystery. */
function BackendStatus() {
  const { data, error } = usePolling(({ signal }) => health.ready({ signal }), {
    intervalMs: 15000,
  });

  if (error) {
    return <Chip size="small" color="error" label="API unreachable" variant="filled" />;
  }
  if (!data) return <Chip size="small" label="Checking…" variant="outlined" />;

  const degraded = data.status !== "ok";
  return (
    <Tooltip
      title={
        `Database: ${data.database ? "connected" : "unreachable"} · ` +
        `workers running: ${data.workers_running ?? 0}` +
        (data.workers_degraded ? ` · degraded: ${data.workers_degraded}` : "")
      }
    >
      <Chip
        size="small"
        color={degraded ? "warning" : "success"}
        variant={degraded ? "filled" : "outlined"}
        label={degraded ? `API ${data.status}` : "API ok"}
      />
    </Tooltip>
  );
}

export function AppLayout({ mode, onToggleMode }) {
  const theme = useTheme();
  const isDesktop = useMediaQuery(theme.breakpoints.up("md"));
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  const drawer = (
    <Box sx={{ display: "flex", flexDirection: "column", height: "100%" }}>
      <Toolbar sx={{ px: 2.5 }}>
        <Box>
          <Typography variant="subtitle1" sx={{ fontWeight: 800, lineHeight: 1.2 }}>
            InsightEye
          </Typography>
          <Typography variant="caption" color="text.secondary">
            Blocked exit detection
          </Typography>
        </Box>
      </Toolbar>
      <Divider />
      <List sx={{ px: 1.5, py: 1.5, flexGrow: 1 }}>
        {NAV_ITEMS.map((item) => (
          <ListItemButton
            key={item.to}
            component={NavLink}
            to={item.to}
            end={item.end}
            onClick={() => setMobileOpen(false)}
            sx={{
              borderRadius: 2,
              mb: 0.5,
              "&.active": {
                bgcolor: "action.selected",
                color: "primary.main",
                "& .MuiListItemIcon-root": { color: "primary.main" },
              },
            }}
          >
            <ListItemIcon sx={{ minWidth: 40 }}>{item.icon}</ListItemIcon>
            <ListItemText primaryTypographyProps={{ fontWeight: 600 }} primary={item.label} />
          </ListItemButton>
        ))}
      </List>
      <Divider />
      <Box sx={{ p: 1.5 }}>
        <ListItemButton
          component="a"
          href="/docs"
          target="_blank"
          rel="noreferrer"
          sx={{ borderRadius: 2 }}
        >
          <ListItemIcon sx={{ minWidth: 40 }}>
            <MenuBookIcon />
          </ListItemIcon>
          <ListItemText
            primary="API docs"
            secondary="FastAPI /docs"
            primaryTypographyProps={{ fontWeight: 600 }}
          />
        </ListItemButton>
      </Box>
    </Box>
  );

  const currentTitle =
    NAV_ITEMS.find((item) =>
      item.end ? location.pathname === item.to : location.pathname.startsWith(item.to)
    )?.label || "Blocked exit detection";

  return (
    <Box sx={{ display: "flex", minHeight: "100vh" }}>
      <AppBar
        position="fixed"
        color="default"
        elevation={0}
        sx={{
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          ml: { md: `${DRAWER_WIDTH}px` },
          borderBottom: 1,
          borderColor: "divider",
          backdropFilter: "blur(8px)",
          bgcolor: (t) =>
            t.palette.mode === "dark" ? "rgba(11,18,32,0.82)" : "rgba(255,255,255,0.86)",
        }}
      >
        <Toolbar>
          <IconButton
            edge="start"
            onClick={() => setMobileOpen(true)}
            sx={{ mr: 2, display: { md: "none" } }}
          >
            <MenuIcon />
          </IconButton>
          <Typography variant="h6" sx={{ flexGrow: 1 }}>
            {currentTitle}
          </Typography>
          <Stack direction="row" spacing={1.5} alignItems="center">
            <WorkspaceSwitcher />
            <BackendStatus />
            <Tooltip title={mode === "dark" ? "Switch to light" : "Switch to dark"}>
              <IconButton onClick={onToggleMode}>
                {mode === "dark" ? <LightModeIcon /> : <DarkModeIcon />}
              </IconButton>
            </Tooltip>
            <UserMenu />
          </Stack>
        </Toolbar>
      </AppBar>

      <Box component="nav" sx={{ width: { md: DRAWER_WIDTH }, flexShrink: { md: 0 } }}>
        <Drawer
          variant={isDesktop ? "permanent" : "temporary"}
          open={isDesktop || mobileOpen}
          onClose={() => setMobileOpen(false)}
          ModalProps={{ keepMounted: true }}
          sx={{
            "& .MuiDrawer-paper": {
              width: DRAWER_WIDTH,
              boxSizing: "border-box",
              borderRight: 1,
              borderColor: "divider",
              backgroundImage: "none",
            },
          }}
        >
          {drawer}
        </Drawer>
      </Box>

      <Box
        component="main"
        sx={{
          flexGrow: 1,
          width: { md: `calc(100% - ${DRAWER_WIDTH}px)` },
          px: { xs: 2, md: 3 },
          pb: 4,
        }}
      >
        <Toolbar />
        <Box sx={{ pt: 3 }}>
          <Outlet />
        </Box>
      </Box>
    </Box>
  );
}

export default AppLayout;
