import { AppProviders } from "@insighteye/ui";
import { AuthProvider } from "./context/AuthContext";
import { PlatformBridge, APP_KEY } from "./platform/PlatformBridge";
import AppRouter from "./routes/AppRouter";

export default function App() {
  return (
    <AppProviders appKey={APP_KEY}>
      <AuthProvider>
        <PlatformBridge>
          <AppRouter />
        </PlatformBridge>
      </AuthProvider>
    </AppProviders>
  );
}
