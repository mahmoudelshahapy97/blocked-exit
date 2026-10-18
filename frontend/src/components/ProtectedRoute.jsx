import { Navigate, Outlet, useLocation } from "react-router-dom";
import { useAuth, roleAtLeast } from "../context/AuthContext";
import { Loading } from "./DataStates";

/**
 * Route guard: renders its children (via <Outlet/>) only once a session is
 * confirmed. Redirects to /login otherwise, remembering where the operator
 * was headed so login can return them there.
 */
export function ProtectedRoute() {
  const { status, isAuthenticated } = useAuth();
  const location = useLocation();

  if (status === "loading") return <Loading label="Checking session…" height="60vh" />;
  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  return <Outlet />;
}

/**
 * Route guard for superadmin-only pages (/admin/users, /admin/workspaces). A
 * workspace role is not enough here — this gates on the account's global role,
 * as the platform's RequireSuperadmin does.
 */
export function SuperadminRoute() {
  const { status, isAuthenticated, isSuperadmin } = useAuth();

  if (status === "loading") return <Loading label="Checking session…" height="60vh" />;
  if (!isAuthenticated) return <Navigate to="/login" replace />;
  if (!isSuperadmin) return <Navigate to="/" replace />;
  return <Outlet />;
}

/**
 * Inline gate for one control, not a whole route — e.g. hiding "Start
 * monitoring" from a viewer while still letting them see the camera detail
 * page. Display-only: the backend re-checks the workspace role on every
 * write regardless, so this cannot be relied on for actual authorization.
 */
export function RoleGate({ minimum, children, fallback = null }) {
  const { workspaceRole } = useAuth();
  return roleAtLeast(workspaceRole, minimum) ? children : fallback;
}

export default ProtectedRoute;
