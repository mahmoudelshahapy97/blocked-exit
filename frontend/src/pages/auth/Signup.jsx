import { useState } from "react";
import { Navigate, Link as RouterLink, useNavigate } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { auth as authApi } from "../../api/endpoints";
import { useAsync } from "../../hooks/useAsync";
import { useAuth } from "../../context/AuthContext";
import { Loading } from "../../components/DataStates";

const PASSWORD_HELP =
  "At least 10 characters, with three of: lowercase, uppercase, digit, symbol.";

export default function Signup() {
  const { signup, error: authError } = useAuth();
  const navigate = useNavigate();

  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [workspaceName, setWorkspaceName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const { data: bootstrap, error: bootstrapError } = useAsync((opts) => authApi.bootstrap(opts));

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    const ok = await signup({ username, email, password, workspaceName });
    setSubmitting(false);
    if (ok) navigate("/", { replace: true });
  };

  if (!bootstrap && !bootstrapError) return <Loading label="Loading…" height="60vh" />;
  // Closed signup: there is nothing to fill in here, accounts come from a superadmin.
  if (bootstrap && !bootstrap.signup_open) return <Navigate to="/login" replace />;
  const isBootstrap = Boolean(bootstrap?.needs_bootstrap);

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        px: 2,
        py: 4,
        bgcolor: "background.default",
      }}
    >
      <Card sx={{ width: "100%", maxWidth: 460 }} elevation={3}>
        <CardContent sx={{ p: 4 }}>
          <Stack spacing={0.5} sx={{ mb: 3 }}>
            <Typography variant="h5" sx={{ fontWeight: 800 }}>
              {isBootstrap ? "Set up InsightEye" : "Create an account"}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {isBootstrap
                ? "This first account becomes the superadmin: it creates workspaces " +
                  "and every other account."
                : "You will join the shared workspace as a member."}
            </Typography>
          </Stack>

          <Box component="form" onSubmit={handleSubmit}>
            <Stack spacing={2.5}>
              {authError && <Alert severity="error">{authError}</Alert>}

              <TextField
                label="Username"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                fullWidth
                required
                helperText="Letters, digits, dot, underscore, hyphen"
              />
              <TextField
                label="Email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                fullWidth
                required
              />
              <TextField
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                fullWidth
                required
                helperText={PASSWORD_HELP}
              />
              {isBootstrap && (
                <TextField
                  label="First workspace name"
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  fullWidth
                  helperText='Optional — defaults to "Default Workspace"'
                />
              )}
              <Button
                type="submit"
                variant="contained"
                size="large"
                disabled={submitting}
                fullWidth
              >
                {submitting ? "Creating account…" : "Create account"}
              </Button>
              <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center" }}>
                Already have an account?{" "}
                <Link component={RouterLink} to="/login">
                  Sign in
                </Link>
              </Typography>
            </Stack>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
