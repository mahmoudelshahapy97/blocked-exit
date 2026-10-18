import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import AppLayout from "../layouts/AppLayout";
import { Loading } from "../components/DataStates";
import { ProtectedRoute, SuperadminRoute } from "../components/ProtectedRoute";

// Code-split per route: the analytics page pulls in chart.js, which has no
// business being in the bundle an operator downloads to watch a live exit.
const Login = lazy(() => import("../pages/auth/Login"));
const Signup = lazy(() => import("../pages/auth/Signup"));
const Dashboard = lazy(() => import("../pages/Dashboard"));
const CameraList = lazy(() => import("../pages/cameras/CameraList"));
const CameraForm = lazy(() => import("../pages/cameras/CameraForm"));
const CameraDetail = lazy(() => import("../pages/cameras/CameraDetail"));
const ZoneEditor = lazy(() => import("../pages/cameras/ZoneEditor"));
const Events = lazy(() => import("../pages/Events"));
const Alerts = lazy(() => import("../pages/Alerts"));
const Analytics = lazy(() => import("../pages/Analytics"));
const WorkspaceSettings = lazy(() => import("../pages/settings/Workspace"));
const AdminUsers = lazy(() => import("../pages/admin/Users"));
const AdminWorkspaces = lazy(() => import("../pages/admin/Workspaces"));
const NotFound = lazy(() => import("../pages/NotFound"));

export function AppRouter({ mode, onToggleMode }) {
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading label="Loading…" height="60vh" />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/signup" element={<Signup />} />

          <Route element={<ProtectedRoute />}>
            <Route element={<AppLayout mode={mode} onToggleMode={onToggleMode} />}>
              <Route path="/" element={<Dashboard />} />

              <Route path="/cameras">
                <Route index element={<CameraList />} />
                <Route path="new" element={<CameraForm />} />
                <Route path=":cameraId" element={<CameraDetail />} />
                <Route path=":cameraId/edit" element={<CameraForm />} />
                <Route path=":cameraId/zone" element={<ZoneEditor />} />
              </Route>

              <Route path="/events" element={<Events />} />
              <Route path="/alerts" element={<Alerts />} />
              <Route path="/analytics" element={<Analytics />} />
              <Route path="/settings/workspace" element={<WorkspaceSettings />} />

              {/* Deep links from the old zone editor used ?camera_id=; keep them working. */}
              <Route path="/zones" element={<Navigate to="/cameras" replace />} />

              <Route element={<SuperadminRoute />}>
                <Route path="/admin/users" element={<AdminUsers />} />
                <Route path="/admin/workspaces" element={<AdminWorkspaces />} />
                <Route path="/admin/workspaces/:workspaceId" element={<AdminWorkspaces />} />
              </Route>

              <Route path="*" element={<NotFound />} />
            </Route>
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default AppRouter;
