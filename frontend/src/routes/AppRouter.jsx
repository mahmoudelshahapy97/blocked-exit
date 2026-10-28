import { Suspense, lazy } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { useTranslation } from "react-i18next";
import DoorFrontIcon from "@mui/icons-material/DoorFront";
import { AuthLayout, Loading, RequireAuth } from "@insighteye/ui";
import AppLayout from "../layouts/AppLayout";

// Code-split per route: the analytics page pulls in chart.js, which has no
// business being in the bundle an operator downloads to watch a live exit.
const Login = lazy(() => import("../pages/auth/Login"));
const Signup = lazy(() => import("../pages/auth/Signup"));
const ForgotPassword = lazy(() => import("../pages/auth/ForgotPassword"));
const Dashboard = lazy(() => import("../pages/Dashboard"));
const CameraList = lazy(() => import("../pages/cameras/CameraList"));
const CameraForm = lazy(() => import("../pages/cameras/CameraForm"));
const CameraDetail = lazy(() => import("../pages/cameras/CameraDetail"));
const ZoneEditor = lazy(() => import("../pages/cameras/ZoneEditor"));
const LiveWall = lazy(() => import("../pages/LiveWall"));
const Events = lazy(() => import("../pages/Events"));
const Alerts = lazy(() => import("../pages/Alerts"));
const Notifications = lazy(() => import("../pages/Notifications"));
const Analytics = lazy(() => import("../pages/Analytics"));
const WorkspaceSettings = lazy(() => import("../pages/settings/Workspace"));
const AdminUsers = lazy(() => import("../pages/admin/Users"));
const AdminWorkspaces = lazy(() => import("../pages/admin/Workspaces"));
const AuditLog = lazy(() => import("../pages/admin/AuditLog"));
const NotFound = lazy(() => import("../pages/NotFound"));

export function AppRouter() {
  const { t } = useTranslation();
  const product = { brand: "InsightEye", tagline: t("product.tagline"), icon: <DoorFrontIcon /> };
  return (
    <BrowserRouter>
      <Suspense fallback={<Loading height="60vh" />}>
        <Routes>
          <Route element={<AuthLayout product={product} />}>
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/forgot-password" element={<ForgotPassword />} />
          </Route>

          <Route
            element={
              <RequireAuth>
                <AppLayout />
              </RequireAuth>
            }
          >
            <Route path="/" element={<Dashboard />} />

            <Route path="/cameras">
              <Route index element={<CameraList />} />
              <Route path="new" element={<CameraForm />} />
              <Route path=":cameraId" element={<CameraDetail />} />
              <Route path=":cameraId/edit" element={<CameraForm />} />
              <Route path=":cameraId/zone" element={<ZoneEditor />} />
            </Route>
            <Route path="/live" element={<LiveWall />} />

            <Route path="/events" element={<Events />} />
            <Route path="/alerts" element={<Alerts />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route path="/analytics" element={<Analytics />} />
            <Route path="/settings/workspace" element={<WorkspaceSettings />} />

            {/* Deep links from the old zone editor used ?camera_id=; keep them working. */}
            <Route path="/zones" element={<Navigate to="/cameras" replace />} />

            <Route
              path="/admin/users"
              element={
                <RequireAuth perm="superadmin">
                  <AdminUsers />
                </RequireAuth>
              }
            />
            <Route
              path="/admin/workspaces"
              element={
                <RequireAuth perm="superadmin">
                  <AdminWorkspaces />
                </RequireAuth>
              }
            />
            <Route
              path="/admin/workspaces/:workspaceId"
              element={
                <RequireAuth perm="superadmin">
                  <AdminWorkspaces />
                </RequireAuth>
              }
            />
            <Route
              path="/audit"
              element={
                <RequireAuth perm="superadmin">
                  <AuditLog />
                </RequireAuth>
              }
            />

            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>
      </Suspense>
    </BrowserRouter>
  );
}

export default AppRouter;
