import { useState } from "react";
import { Navigate, Link as RouterLink, useLocation, useNavigate } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Link from "@mui/material/Link";
import Stack from "@mui/material/Stack";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";

import { errorMessage } from "../../api/client";
import { auth as authApi } from "../../api/endpoints";
import { useAsync } from "../../hooks/useAsync";
import { Loading } from "../../components/DataStates";
import { PASSWORD_HELP } from "../../utils/constants";

/**
 * "Forgot your password?" in two steps: ask for a code by email, then enter
 * the code with the new password. The API checks both in one call, and answers
 * the first step the same way whether or not the account exists.
 */
export default function ForgotPassword() {
  const navigate = useNavigate();
  const location = useLocation();
  const { data: bootstrap, error: bootstrapError } = useAsync((opts) => authApi.bootstrap(opts));

  const [step, setStep] = useState("email");
  const [email, setEmail] = useState(location.state?.email || "");
  const [code, setCode] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [info, setInfo] = useState(null);
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  if (!bootstrap && !bootstrapError) return <Loading label="Loading…" height="60vh" />;
  // Without SMTP there is no code to send; the login page hides the link too.
  if (bootstrap && !bootstrap.password_reset) return <Navigate to="/login" replace />;

  const requestCode = async (event) => {
    event?.preventDefault();
    if (!email.trim()) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await authApi.forgotPassword(email.trim());
      setInfo(result.message);
      setCode("");
      setStep("code");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setSubmitting(false);
    }
  };

  const resetPassword = async (event) => {
    event.preventDefault();
    if (password !== confirm) {
      setError("The two passwords do not match.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const result = await authApi.resetPassword({
        email: email.trim(),
        code: code.trim(),
        newPassword: password,
      });
      navigate("/login", { replace: true, state: { notice: result.message } });
    } catch (err) {
      setError(errorMessage(err));
      setSubmitting(false);
    }
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
              Reset your password
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {step === "email"
                ? "Enter your account's email and we will send you a code."
                : `Enter the code sent to ${email.trim()} and choose a new password.`}
            </Typography>
          </Stack>

          {step === "email" ? (
            <Box component="form" onSubmit={requestCode}>
              <Stack spacing={2.5}>
                {error && <Alert severity="error">{error}</Alert>}
                <TextField
                  label="Email"
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoComplete="email"
                  autoFocus
                  fullWidth
                  required
                />
                <Button
                  type="submit"
                  variant="contained"
                  size="large"
                  disabled={submitting}
                  fullWidth
                >
                  {submitting ? "Sending…" : "Send code"}
                </Button>
                <Link
                  component={RouterLink}
                  to="/login"
                  variant="body2"
                  sx={{ alignSelf: "center" }}
                >
                  Back to sign in
                </Link>
              </Stack>
            </Box>
          ) : (
            <Box component="form" onSubmit={resetPassword}>
              <Stack spacing={2.5}>
                {info && !error && <Alert severity="info">{info}</Alert>}
                {error && <Alert severity="error">{error}</Alert>}
                <TextField
                  label="Code from the email"
                  value={code}
                  onChange={(e) => setCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  inputProps={{ inputMode: "numeric", autoComplete: "one-time-code" }}
                  autoFocus
                  fullWidth
                  required
                />
                <TextField
                  label="New password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  helperText={PASSWORD_HELP}
                  fullWidth
                  required
                />
                <TextField
                  label="Repeat new password"
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  fullWidth
                  required
                />
                <Button
                  type="submit"
                  variant="contained"
                  size="large"
                  disabled={submitting}
                  fullWidth
                >
                  {submitting ? "Saving…" : "Set new password"}
                </Button>
                <Stack direction="row" justifyContent="space-between">
                  <Link
                    component="button"
                    type="button"
                    variant="body2"
                    onClick={requestCode}
                    disabled={submitting}
                  >
                    Send a new code
                  </Link>
                  <Link component={RouterLink} to="/login" variant="body2">
                    Back to sign in
                  </Link>
                </Stack>
              </Stack>
            </Box>
          )}
        </CardContent>
      </Card>
    </Box>
  );
}
