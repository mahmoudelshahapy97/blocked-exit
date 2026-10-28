import { useMemo } from "react";
import { PlatformProvider, threeOfFourPolicy } from "@insighteye/ui";
import { audit, auth as authApi, cameras, health, monitoring, notifications } from "../api/endpoints";
import { getAccessToken } from "../api/tokenStore";
import { errorMessage } from "../api/client";
import { useAuth } from "../context/AuthContext";

export const APP_KEY = "blocked-exit";

/**
 * This console's side of the @insighteye/ui platform adapter (see
 * packages/insighteye-ui/README.md). Two things differ from the other
 * consoles: the active workspace is stored on the server (switching calls
 * POST /workspaces/{id}/activate), and roles are a platform role
 * (superadmin/user) plus a role per workspace (viewer/member/admin).
 */
export function PlatformBridge({ children }) {
  const authState = useAuth();

  const value = useMemo(() => {
    const { user, workspaces, activeWorkspace, isSuperadmin, canResolve, canManage, workspaceRole } = authState;
    const status = authState.status === "authenticated" ? "authed" : authState.status === "anonymous" ? "anon" : "loading";
    const shape = (w) => w && { workspace_id: w.id, name: w.name, is_active: w.is_active !== false, camera_count: w.camera_count };
    return {
      appKey: APP_KEY,
      passwordPolicy: threeOfFourPolicy,
      auth: {
        user,
        status,
        login: (username, password) => authState.login({ username, password }),
        logout: authState.logout,
        refreshProfile: authState.refreshProfile,
        // viewer: anyone in the workspace; operator: may triage (member+);
        // admin: may manage the workspace; superadmin: the platform role.
        can: (perm) => {
          if (!user) return false;
          if (perm === "superadmin") return isSuperadmin;
          if (perm === "admin") return isSuperadmin || canManage;
          if (perm === "operator") return isSuperadmin || canResolve;
          return true;
        },
        roleOf: () => (isSuperadmin ? "superadmin" : workspaceRole || "user"),
        getAccessToken,
      },
      workspace: user
        ? {
            workspaces: (workspaces || []).map(shape),
            active: shape(activeWorkspace),
            ready: status === "authed",
            error: null,
            setActive: (id) => authState.switchWorkspace(id),
            reload: authState.refreshProfile,
          }
        : null,
      emailAlerts: {
        eligible: () => true,
        enabled: (u) => Boolean(u?.notify_email),
        set: (on) => authApi.updateMe({ notify_email: on }),
      },
      api: {
        health: async (opts) => {
          const ready = await health.ready(opts);
          return {
            status: ready.status === "ok" || ready.status === "ready" ? "healthy" : ready.status,
            db_connection_ok: ready.database !== false,
            workers: { running: ready.workers_running ?? 0, total: ready.workers_total ?? 0 },
            version: ready.version,
          };
        },
        authOptions: (opts) =>
          authApi.bootstrap(opts).then((b) => ({
            password_reset: b.password_reset,
            signup: b.signup_open,
            bootstrap: b.needs_bootstrap,
            notify_email: b.notify_email,
          })),
        changePassword: (current, next) =>
          authApi.changePassword({ current_password: current, new_password: next }),
        forgotPassword: authApi.forgotPassword,
        resetPassword: authApi.resetPassword,
        notifications,
        audit,
        cameras: {
          list: async () => {
            const [list, statuses] = await Promise.all([cameras.list(), monitoring.statusAll().catch(() => [])]);
            const running = new Set((statuses || []).filter((s) => s.worker_state === "running").map((s) => s.camera_id));
            return (list?.items || list || []).map((c) => ({
              camera_id: c.id,
              name: c.name,
              location: c.location,
              running: running.has(c.id),
            }));
          },
          // Images authenticate by header here, so the wall fetches each
          // frame and shows it as an object URL.
          loadSnapshot: (id, { signal } = {}) => monitoring.snapshot(id, { signal }),
          probe: cameras.probe,
          probeAll: cameras.probeAll,
        },
        errorMessage,
      },
    };
  }, [authState]);

  return <PlatformProvider value={value}>{children}</PlatformProvider>;
}

export default PlatformBridge;
