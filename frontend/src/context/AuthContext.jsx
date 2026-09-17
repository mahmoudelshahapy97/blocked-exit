import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import { auth as authApi } from "../api/endpoints";
import { errorMessage } from "../api/client";
import {
  clearSession,
  getActiveWorkspaceId,
  getStoredRefreshToken,
  setActiveWorkspaceId,
  setSession,
  subscribe,
} from "../api/tokenStore";

const AuthContext = createContext(null);

/**
 * Session state for the whole app: who is logged in, which workspace is
 * active, and the actions that change either. Wraps ../api/tokenStore (plain
 * module state, so axios interceptors can read it outside React) and adds the
 * one thing that module cannot: re-rendering components when it changes.
 */
export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [memberships, setMemberships] = useState([]);
  const [activeWorkspaceId, setActiveWorkspaceIdState] = useState(getActiveWorkspaceId());
  const [status, setStatus] = useState("loading"); // loading | authenticated | anonymous
  const [error, setError] = useState(null);

  // tokenStore notifies on every setSession/clearSession/workspace change;
  // mirror the workspace id into component state so switching re-renders.
  useEffect(() => subscribe(() => setActiveWorkspaceIdState(getActiveWorkspaceId())), []);

  const loadProfile = useCallback(async () => {
    const profile = await authApi.me();
    setUser(profile);
    setMemberships(profile.memberships || []);
    setSession({ user: profile });

    // No workspace selected yet (fresh login, or first load after a reload):
    // default to the account's own default, falling back to the first
    // membership so a user with no default configured still sees something.
    const stored = getActiveWorkspaceId();
    const known = (profile.memberships || []).some((m) => m.workspace_id === stored);
    if (!known) {
      const fallback = profile.default_workspace_id ?? profile.memberships?.[0]?.workspace_id ?? null;
      setActiveWorkspaceId(fallback);
    }
    return profile;
  }, []);

  // On first mount, a stored refresh token means "try to resume the
  // session" — the axios interceptor mints a new access token from it on the
  // first authenticated call, so calling /auth/me is enough to both refresh
  // and hydrate.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getStoredRefreshToken()) {
        setStatus("anonymous");
        return;
      }
      try {
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

  const login = useCallback(
    async ({ username, password, workspaceId }) => {
      setError(null);
      try {
        const pair = await authApi.login({
          username,
          password,
          workspace_id: workspaceId,
        });
        setSession({ accessToken: pair.access_token, refreshToken: pair.refresh_token });
        await loadProfile();
        setStatus("authenticated");
        return true;
      } catch (err) {
        setError(errorMessage(err));
        return false;
      }
    },
    [loadProfile]
  );

  const signup = useCallback(
    async ({ username, email, password, fullName, workspaceName }) => {
      setError(null);
      try {
        const pair = await authApi.signup({
          username,
          email,
          password,
          full_name: fullName || undefined,
          workspace_name: workspaceName || undefined,
        });
        setSession({ accessToken: pair.access_token, refreshToken: pair.refresh_token });
        await loadProfile();
        setStatus("authenticated");
        return true;
      } catch (err) {
        setError(errorMessage(err));
        return false;
      }
    },
    [loadProfile]
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
    setMemberships([]);
    setStatus("anonymous");
  }, []);

  const switchWorkspace = useCallback((workspaceId) => {
    setActiveWorkspaceId(workspaceId);
  }, []);

  const refreshProfile = useCallback(() => loadProfile(), [loadProfile]);

  const activeMembership = useMemo(
    () => memberships.find((m) => m.workspace_id === activeWorkspaceId) || null,
    [memberships, activeWorkspaceId]
  );

  const value = useMemo(
    () => ({
      user,
      memberships,
      activeWorkspaceId,
      activeMembership,
      // "owner" outranks everything below it — see app.core.enums.WorkspaceRole
      // on the backend, which this mirrors for UI gating only (the backend
      // re-checks on every request regardless).
      workspaceRole: activeMembership?.role ?? null,
      isPlatformAdmin: user?.role === "admin",
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
      memberships,
      activeWorkspaceId,
      activeMembership,
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

const ROLE_RANK = { viewer: 0, operator: 1, admin: 2, owner: 3 };

/** Mirrors WorkspaceRole.can_act_as on the backend — display-only gating. */
export function roleAtLeast(role, minimum) {
  if (!role) return false;
  return (ROLE_RANK[role] ?? -1) >= (ROLE_RANK[minimum] ?? Infinity);
}

export default AuthContext;
