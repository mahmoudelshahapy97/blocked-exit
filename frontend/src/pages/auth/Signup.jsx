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
import { useTranslation } from "react-i18next";

export default function Signup() {
  const { t } = useTranslation();
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

  if (!bootstrap && !bootstrapError) return <Loading label={t("signup.loading")} height="60vh" />;
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
              {isBootstrap ? t("signup.setUpInsighteye") : t("signup.createAnAccount")}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {isBootstrap
                ? t("signup.firstAccountIsSuperadmin")
                : t("signup.youWillJoinTheShared")}
            </Typography>
          </Stack>

          <Box component="form" onSubmit={handleSubmit}>
            <Stack spacing={2.5}>
              {authError && <Alert severity="error">{authError}</Alert>}

              <TextField
                label={t("signup.username")}
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                autoFocus
                fullWidth
                required
                helperText={t("signup.lettersDigitsDotUnderscoreHyphen")}
              />
              <TextField
                label={t("signup.email")}
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                fullWidth
                required
              />
              <TextField
                label={t("signup.password")}
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                fullWidth
                required
                helperText={t("common:password.hintThreeOfFour")}
              />
              {isBootstrap && (
                <TextField
                  label={t("signup.firstWorkspaceName")}
                  value={workspaceName}
                  onChange={(e) => setWorkspaceName(e.target.value)}
                  fullWidth
                  helperText={t("signup.optionalDefaultsToDefaultWorkspace")}
                />
              )}
              <Button
                type="submit"
                variant="contained"
                size="large"
                disabled={submitting}
                fullWidth
              >
                {submitting ? t("signup.creatingAccount") : t("signup.createAccount")}
              </Button>
              <Typography variant="body2" color="text.secondary" sx={{ textAlign: "center" }}>
                {t("signup.alreadyHaveAnAccount")}{" "}
                <Link component={RouterLink} to="/login">
                  {t("signup.signIn")}
                </Link>
              </Typography>
            </Stack>
          </Box>
        </CardContent>
      </Card>
    </Box>
  );
}
