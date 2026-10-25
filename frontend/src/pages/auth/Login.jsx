import { useState } from "react";
import { Link as RouterLink, useLocation, useNavigate } from "react-router-dom";
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

export default function Login() {
  const { login, error: authError } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const from = location.state?.from?.pathname || "/";
  // Set by the password reset page on its way back here.
  const notice = location.state?.notice;
  // Accounts are issued by a superadmin; signup is only offered while the
  // server says it is open (first-run bootstrap, or ALLOW_OPEN_SIGNUP).
  const { data: bootstrap } = useAsync((opts) => authApi.bootstrap(opts));

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    const ok = await login({ username, password });
    setSubmitting(false);
    if (ok) navigate(from, { replace: true });
  };

  return (
    <Box
      sx={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        px: 2,
        bgcolor: "background.default",
      }}
    >
      <Card sx={{ width: "100%", maxWidth: 420 }} elevation={3}>
        <CardContent sx={{ p: 4 }}>
          <Stack spacing={0.5} sx={{ mb: 3 }}>
            <Typography variant="h5" sx={{ fontWeight: 800 }}>
              InsightEye
            </Typography>
            <Typography variant="body2" color="text.secondary">
              Sign in to the blocked-exit console
            </Typography>
          </Stack>

          <Box component="form" onSubmit={handleSubmit}>
            <Stack spacing={2.5}>
              {notice && !authError && <Alert severity="success">{notice}</Alert>}
              {authError && <Alert severity="error">{authError}</Alert>}

              <TextField
                label="Username or email"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                fullWidth
                required
              />
              <TextField
                label="Password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
                fullWidth
                required
              />
              {bootstrap?.password_reset && (
                <Link
                  component={RouterLink}
                  to="/forgot-password"
                  // An email typed as the login carries over to the reset form.
                  state={{ email: username.includes("@") ? username.trim() : "" }}
                  variant="body2"
                  sx={{ alignSelf: "flex-end" }}
                >
                  Forgot your password?
                </Link>
              )}
              <Button
                type="submit"
                variant="contained"
                size="large"
                disabled={submitting}
                fullWidth
              >
                {submitting ? "Signing in…" : "Sign in"}
              </Button>
              {bootstrap?.needs_bootstrap ? (
                <Alert severity="info">
                  This deployment has no accounts yet.{" "}
                  <Link component={RouterLink} to="/signup">
                    Create the administrator account
                  </Link>
                  .
                </Alert>
              ) : (
                <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center" }}>
                  No account?{" "}
                  {bootstrap?.signup_open ? (
                    <Link component={RouterLink} to="/signup">
                      Create one
                    </Link>
                  ) : (
                    "Contact your administrator."
                  )}
                </Typography>
              )}
            </Stack>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
