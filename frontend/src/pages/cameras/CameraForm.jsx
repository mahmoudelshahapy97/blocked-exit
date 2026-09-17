import { useEffect, useMemo, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Divider from "@mui/material/Divider";
import FormControlLabel from "@mui/material/FormControlLabel";
import Grid from "@mui/material/Grid2";
import InputAdornment from "@mui/material/InputAdornment";
import MenuItem from "@mui/material/MenuItem";
import Stack from "@mui/material/Stack";
import Switch from "@mui/material/Switch";
import TextField from "@mui/material/TextField";
import Typography from "@mui/material/Typography";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";

import { errorMessage } from "../../api/client";
import { cameras as camerasApi } from "../../api/endpoints";
import { useAsync } from "../../hooks/useAsync";
import { useToast } from "../../components/Toast";
import { ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import { STRATEGY } from "../../utils/constants";

const EMPTY = {
  name: "",
  location: "",
  rtsp_url: "",
  enabled: true,
  strategy: STRATEGY.ZONE_BASED,
  clear_min_pct: "",
  full_max_pct: "",
  confirm_seconds: "",
  clear_seconds: "",
  process_fps: "",
};

/** Per-camera overrides. Empty means "inherit the global .env value", which is
 *  a different thing from zero, so blanks must be sent as null, not 0. */
const NUMERIC_FIELDS = [
  "clear_min_pct",
  "full_max_pct",
  "confirm_seconds",
  "clear_seconds",
  "process_fps",
];

function validate(values) {
  const errors = {};
  if (!values.name.trim()) errors.name = "Required";
  if (values.name.length > 120) errors.name = "At most 120 characters";
  if (!values.rtsp_url.trim()) errors.rtsp_url = "Required";

  NUMERIC_FIELDS.forEach((field) => {
    const raw = values[field];
    if (raw === "" || raw === null) return;
    const value = Number(raw);
    if (Number.isNaN(value)) errors[field] = "Must be a number";
  });

  const clearMin = values.clear_min_pct === "" ? null : Number(values.clear_min_pct);
  const fullMax = values.full_max_pct === "" ? null : Number(values.full_max_pct);
  if (clearMin !== null && (clearMin < 0 || clearMin > 100))
    errors.clear_min_pct = "Between 0 and 100";
  if (fullMax !== null && (fullMax < 0 || fullMax > 100))
    errors.full_max_pct = "Between 0 and 100";
  // The backend validates each bound separately but never their relationship;
  // inverted thresholds would silently make PARTIAL unreachable.
  if (clearMin !== null && fullMax !== null && fullMax >= clearMin) {
    errors.full_max_pct = "Must be below the CLEAR threshold";
  }
  if (values.process_fps !== "" && (Number(values.process_fps) <= 0 || Number(values.process_fps) > 60)) {
    errors.process_fps = "Between 0 and 60";
  }
  return errors;
}

export default function CameraForm() {
  const { cameraId } = useParams();
  const isEdit = Boolean(cameraId);
  const navigate = useNavigate();
  const toast = useToast();

  const [values, setValues] = useState(EMPTY);
  const [errors, setErrors] = useState({});
  const [saving, setSaving] = useState(false);

  const {
    data: camera,
    error: loadError,
    loading,
    refresh,
  } = useAsync(() => camerasApi.get(cameraId), [cameraId], { enabled: isEdit });

  useEffect(() => {
    if (!camera) return;
    setValues({
      name: camera.name ?? "",
      location: camera.location ?? "",
      rtsp_url: camera.rtsp_url ?? "",
      enabled: camera.enabled ?? true,
      strategy: camera.strategy ?? STRATEGY.ZONE_BASED,
      clear_min_pct: camera.clear_min_pct ?? "",
      full_max_pct: camera.full_max_pct ?? "",
      confirm_seconds: camera.confirm_seconds ?? "",
      clear_seconds: camera.clear_seconds ?? "",
      process_fps: camera.process_fps ?? "",
    });
  }, [camera]);

  const setField = (field) => (event) => {
    const value = event.target.type === "checkbox" ? event.target.checked : event.target.value;
    setValues((current) => ({ ...current, [field]: value }));
    setErrors((current) => ({ ...current, [field]: undefined }));
  };

  const payload = useMemo(() => {
    const body = {
      name: values.name.trim(),
      location: values.location.trim() || null,
      rtsp_url: values.rtsp_url.trim(),
      enabled: values.enabled,
      strategy: values.strategy,
    };
    NUMERIC_FIELDS.forEach((field) => {
      body[field] = values[field] === "" ? null : Number(values[field]);
    });
    return body;
  }, [values]);

  const handleSubmit = async (event) => {
    event.preventDefault();
    const found = validate(values);
    setErrors(found);
    if (Object.keys(found).length) return;

    setSaving(true);
    try {
      if (isEdit) {
        await camerasApi.update(cameraId, payload);
        toast.success("Camera updated");
        navigate(`/cameras/${cameraId}`);
      } else {
        const created = await camerasApi.create(payload);
        toast.success(`Created ${created.name}`);
        // Zone-based is useless without a region, so land the operator on the
        // editor rather than making them discover that step themselves.
        navigate(
          created.strategy === STRATEGY.ZONE_BASED
            ? `/cameras/${created.id}/zone`
            : `/cameras/${created.id}`
        );
      }
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  if (isEdit && loading) return <Loading label="Loading camera…" height={320} />;

  return (
    <Box component="form" onSubmit={handleSubmit} noValidate>
      <PageHeader
        title={isEdit ? `Edit ${camera?.name || "camera"}` : "Add an exit"}
        subtitle="One camera watches one emergency exit."
        actions={
          <Button startIcon={<ArrowBackIcon />} component={RouterLink} to="/cameras" color="inherit">
            Back
          </Button>
        }
      />

      <ErrorState error={loadError} onRetry={refresh} title="Could not load this camera" />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" gutterBottom>
                Identity and source
              </Typography>
              <Stack spacing={2.5} sx={{ mt: 2 }}>
                <TextField
                  label="Name"
                  required
                  fullWidth
                  value={values.name}
                  onChange={setField("name")}
                  error={Boolean(errors.name)}
                  helperText={errors.name || "Must be unique — the backend rejects duplicates."}
                />
                <TextField
                  label="Location"
                  fullWidth
                  value={values.location}
                  onChange={setField("location")}
                  placeholder="Building 1, Floor 1"
                />
                <TextField
                  label="Stream source"
                  required
                  fullWidth
                  value={values.rtsp_url}
                  onChange={setField("rtsp_url")}
                  error={Boolean(errors.rtsp_url)}
                  helperText={
                    errors.rtsp_url ||
                    "rtsp://user:pass@host:554/stream1 — or a path to a local video file to exercise the pipeline without a camera."
                  }
                />
                <TextField
                  select
                  label="Detection strategy"
                  fullWidth
                  value={values.strategy}
                  onChange={setField("strategy")}
                  helperText={
                    values.strategy === STRATEGY.ZONE_BASED
                      ? "Detects obstacles and measures what overlaps the exit region you draw. Works with the stock COCO weights."
                      : "Compares the visible door against a stored unobstructed reference. Needs door weights (DOOR_MODEL_PATH) and a reference capture."
                  }
                >
                  <MenuItem value={STRATEGY.ZONE_BASED}>Zone based</MenuItem>
                  <MenuItem value={STRATEGY.DOOR_CENTRIC}>Door centric</MenuItem>
                </TextField>
                <FormControlLabel
                  control={<Switch checked={values.enabled} onChange={setField("enabled")} />}
                  label="Enabled"
                />
                <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5 }}>
                  Enabled cameras start their worker as soon as they are saved, and again
                  whenever the backend restarts.
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 5 }}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2">Per-camera overrides</Typography>
              <Typography variant="caption" color="text.secondary">
                Leave a field empty to inherit the global value from the backend&apos;s .env.
              </Typography>
              <Divider sx={{ my: 2 }} />
              <Stack spacing={2.5}>
                <TextField
                  label="CLEAR threshold"
                  type="number"
                  fullWidth
                  value={values.clear_min_pct}
                  onChange={setField("clear_min_pct")}
                  error={Boolean(errors.clear_min_pct)}
                  helperText={errors.clear_min_pct || "At or above this accessible %, the exit is CLEAR."}
                  slotProps={{
                    input: { endAdornment: <InputAdornment position="end">%</InputAdornment> },
                  }}
                />
                <TextField
                  label="FULL threshold"
                  type="number"
                  fullWidth
                  value={values.full_max_pct}
                  onChange={setField("full_max_pct")}
                  error={Boolean(errors.full_max_pct)}
                  helperText={errors.full_max_pct || "Below this accessible %, the exit counts as FULL."}
                  slotProps={{
                    input: { endAdornment: <InputAdornment position="end">%</InputAdornment> },
                  }}
                />
                <TextField
                  label="Confirm seconds"
                  type="number"
                  fullWidth
                  value={values.confirm_seconds}
                  onChange={setField("confirm_seconds")}
                  error={Boolean(errors.confirm_seconds)}
                  helperText={
                    errors.confirm_seconds ||
                    "How long an obstruction must persist before it is believed — this is what ignores passers-by."
                  }
                />
                <TextField
                  label="Clear seconds"
                  type="number"
                  fullWidth
                  value={values.clear_seconds}
                  onChange={setField("clear_seconds")}
                  error={Boolean(errors.clear_seconds)}
                  helperText={errors.clear_seconds || "How long it must stay clear before the event closes."}
                />
                <TextField
                  label="Process FPS"
                  type="number"
                  fullWidth
                  value={values.process_fps}
                  onChange={setField("process_fps")}
                  error={Boolean(errors.process_fps)}
                  helperText={
                    errors.process_fps ||
                    "Frames analysed per second — not the stream's own frame rate. Higher costs CPU per camera."
                  }
                />
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {values.strategy === STRATEGY.DOOR_CENTRIC && (
        <Alert severity="info" sx={{ mt: 2 }}>
          Door-centric needs door-only weights configured on the backend
          (DOOR_MODEL_PATH) and a reference frame captured while the exit is clear.
          Without them the registry falls back to the default strategy rather than failing.
        </Alert>
      )}

      <Stack direction="row" spacing={1.5} sx={{ mt: 3 }}>
        <Button type="submit" variant="contained" size="large" disabled={saving}>
          {saving ? "Saving…" : isEdit ? "Save changes" : "Create exit"}
        </Button>
        <Button component={RouterLink} to="/cameras" color="inherit" size="large">
          Cancel
        </Button>
      </Stack>
    </Box>
  );
}
