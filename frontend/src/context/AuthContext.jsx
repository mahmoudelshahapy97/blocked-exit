import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { auth as authApi, workspaces as workspacesApi } from "../api/endpoints";
import { errorMessage, refreshAccessToken } from "../api/client";
import {
  clearSession,
  getAccessToken,
  getStoredRefreshToken,
  setSession,
} from "../api/tokenStore";

const AuthContext = createContext(null);

/**
 * Session state for the whole app: who is logged in, which workspace they are
 * working in, and what they may do there.
 *
 * Like the platform, the active workspace lives on the server (one per user,
 * shared by every tab) and is switched with POST /workspaces/{id}/activate.
 * Switching bumps `workspaceVersion`, which AppLayout uses as the page key, so
 * every page remounts and refetches against the new workspace.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [workspaces, setWorkspaces] = useState([]);
  const [permissions, setPermissions] = useState(null);
  const [workspaceVersion, setWorkspaceVersion] = useState(0);
  const [status, setStatus] = useState("loading"); // loading | authenticated | anonymous
  const [error, setError] = useState(null);

  const loadProfile = useCallback(async () => {
    const profile = await authApi.me();
    setUser(profile);
    setSession({ user: profile });
    const [list, perms] = await Promise.all([
      workspacesApi.list().catch(() => []),
      // 404 when the account belongs nowhere yet; the layout says so.
      workspacesApi.permissions().catch(() => null),
    ]);
    setWorkspaces(list);
    setPermissions(perms);
    return profile;
  }, []);

  // On first mount, a stored refresh token means "try to resume the
  // session". The access token lives in memory only, so a reloaded tab has
  // none: mint one first rather than letting /auth/me bounce off a 401.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getStoredRefreshToken()) {
        setStatus("anonymous");
        return;
      }
      try {
        if (!getAccessToken()) await refreshAccessToken();
        await loadProfile();
        if (!cancelled) setStatus("authenticated");
      } catch {
        if (!cancelled) {
          clearSession();
          setStatus("anonymous");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [loadProfile]);

  const startSession = useCallback(
    async (pair) => {
      setSession({ accessToken: pair.access_token, refreshToken: pair.refresh_token });
      await loadProfile();
      setStatus("authenticated");
    },
    [loadProfile]
  );

  const login = useCallback(
    async ({ username, password }) => {
      setError(null);
      try {
        await startSession(await authApi.login({ username, password }));
        return { success: true };
      } catch (err) {
        const message = errorMessage(err);
        setError(message);
        return { success: false, message };
      }
    },
    [startSession]
  );

  const signup = useCallback(
    async ({ username, email, password, fullName, workspaceName }) => {
      setError(null);
      try {
        await startSession(
          await authApi.signup({
            username,
            email,
            password,
            full_name: fullName || undefined,
            workspace_name: workspaceName || undefined,
          })
        );
        return true;
      } catch (err) {
        setError(errorMessage(err));
        return false;
      }
    },
    [startSession]
  );

  const logout = useCallback(async () => {
    const refreshToken = getStoredRefreshToken();
    try {
      await authApi.logout(refreshToken);
    } catch {
      // Logging out client-side matters more than the server call succeeding.
    }
    clearSession();
    setUser(null);
    setWorkspaces([]);
    setPermissions(null);
    setStatus("anonymous");
  }, []);

  const switchWorkspace = useCallback(
    async (workspaceId) => {
      await workspacesApi.activate(workspaceId);
      await loadProfile();
      setWorkspaceVersion((v) => v + 1);
    },
    [loadProfile]
  );

  const refreshProfile = useCallback(() => loadProfile(), [loadProfile]);

  const activeWorkspaceId = user?.active_workspace_id ?? null;
  const activeWorkspace = useMemo(
    () => workspaces.find((w) => w.id === activeWorkspaceId) || null,
    [workspaces, activeWorkspaceId]
  );

  const value = useMemo(
    () => ({
      user,
      workspaces,
      activeWorkspaceId,
      activeWorkspace,
      workspaceVersion,
      permissions,
      // Display-only gating; the backend re-checks the role on every request.
      workspaceRole: permissions?.role ?? null,
      canResolve: Boolean(permissions?.can_resolve),
      canManage: Boolean(permissions?.can_manage),
      isSuperadmin: user?.role === "superadmin",
      status,
      isAuthenticated: status === "authenticated",
      error,
      login,
      signup,
      logout,
      switchWorkspace,
      refreshProfile,
    }),
    [
      user,
      workspaces,
      activeWorkspaceId,
      activeWorkspace,
      workspaceVersion,
      permissions,
      status,
      error,
      login,
      signup,
      logout,
      switchWorkspace,
      refreshProfile,
    ]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
};

const ROLE_RANK = { viewer: 0, member: 1, admin: 2 };

/** Mirrors WorkspaceRole.can_act_as on the backend — display-only gating. */
export function roleAtLeast(role, minimum) {
  if (!role) return false;
  return (ROLE_RANK[role] ?? -1) >= (ROLE_RANK[minimum] ?? Infinity);
}

export default AuthContext;
