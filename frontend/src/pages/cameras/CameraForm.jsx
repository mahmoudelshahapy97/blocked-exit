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
import { useTranslation } from "react-i18next";
import i18n from "i18next";

/** Where the exit is, coarsest first — the platform's camera hierarchy. The
 *  Events and Analytics filters cascade through these in this order. */
const HIERARCHY_FIELDS = [
  { field: "location", get label() { return i18n.t("cameraForm.location"); }, get placeholder() { return i18n.t("cameraForm.phLocation"); }, maxLength: 255 },
  { field: "area", get label() { return i18n.t("cameraForm.area"); }, get placeholder() { return i18n.t("cameraForm.phArea"); }, maxLength: 100 },
  { field: "building", get label() { return i18n.t("cameraForm.building"); }, get placeholder() { return i18n.t("cameraForm.phBuilding"); }, maxLength: 100 },
  { field: "floor_level", get label() { return i18n.t("cameraForm.floor"); }, get placeholder() { return i18n.t("cameraForm.phFloor"); }, maxLength: 20 },
  { field: "zone", get label() { return i18n.t("cameraForm.zone"); }, get placeholder() { return i18n.t("cameraForm.phZone"); }, maxLength: 100 },
];

const EMPTY = {
  name: "",
  location: "",
  area: "",
  building: "",
  floor_level: "",
  zone: "",
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
  if (!values.name.trim()) errors.name = i18n.t("cameraForm.required");
  if (values.name.length > 120) errors.name = i18n.t("cameraForm.atMost120Characters");
  if (!values.rtsp_url.trim()) errors.rtsp_url = i18n.t("cameraForm.required");

  NUMERIC_FIELDS.forEach((field) => {
    const raw = values[field];
    if (raw === "" || raw === null) return;
    const value = Number(raw);
    if (Number.isNaN(value)) errors[field] = i18n.t("cameraForm.mustBeANumber");
  });

  const clearMin = values.clear_min_pct === "" ? null : Number(values.clear_min_pct);
  const fullMax = values.full_max_pct === "" ? null : Number(values.full_max_pct);
  if (clearMin !== null && (clearMin < 0 || clearMin > 100))
    errors.clear_min_pct = i18n.t("cameraForm.between0And100");
  if (fullMax !== null && (fullMax < 0 || fullMax > 100))
    errors.full_max_pct = i18n.t("cameraForm.between0And100");
  // The backend validates each bound separately but never their relationship;
  // inverted thresholds would silently make PARTIAL unreachable.
  if (clearMin !== null && fullMax !== null && fullMax >= clearMin) {
    errors.full_max_pct = i18n.t("cameraForm.mustBeBelowTheClear");
  }
  if (values.process_fps !== "" && (Number(values.process_fps) <= 0 || Number(values.process_fps) > 60)) {
    errors.process_fps = i18n.t("cameraForm.between0And60");
  }
  return errors;
}

export default function CameraForm() {
  const { t } = useTranslation();
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
      area: camera.area ?? "",
      building: camera.building ?? "",
      floor_level: camera.floor_level ?? "",
      zone: camera.zone ?? "",
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
      rtsp_url: values.rtsp_url.trim(),
      enabled: values.enabled,
      strategy: values.strategy,
    };
    HIERARCHY_FIELDS.forEach(({ field }) => {
      body[field] = values[field].trim() || null;
    });
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
        toast.success(t("cameraForm.cameraUpdated"));
        navigate(`/cameras/${cameraId}`);
      } else {
        const created = await camerasApi.create(payload);
        toast.success(t("cameraForm.createdName", { name: created.name }));
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

  if (isEdit && loading) return <Loading label={t("cameraForm.loadingCamera")} height={320} />;

  return (
    <Box component="form" onSubmit={handleSubmit} noValidate>
      <PageHeader
        title={isEdit ? t("cameraForm.editV0", { v0: camera?.name || "camera" }) : t("cameraForm.addAnExit")}
        subtitle={t("cameraForm.oneCameraWatchesOneEmergency")}
        actions={
          <Button startIcon={<ArrowBackIcon />} component={RouterLink} to="/cameras" color="inherit">
            {t("cameraForm.back")}
          </Button>
        }
      />

      <ErrorState error={loadError} onRetry={refresh} title={t("cameraForm.couldNotLoadThisCamera")} />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, md: 7 }}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" gutterBottom>
                {t("cameraForm.identityAndSource")}
              </Typography>
              <Stack spacing={2.5} sx={{ mt: 2 }}>
                <TextField
                  label={t("cameraForm.name")}
                  required
                  fullWidth
                  value={values.name}
                  onChange={setField("name")}
                  error={Boolean(errors.name)}
                  helperText={errors.name || t("cameraForm.mustBeUniqueTheBackend")}
                />
                <Grid container spacing={2}>
                  {HIERARCHY_FIELDS.map(({ field, label, placeholder, maxLength }) => (
                    <Grid key={field} size={{ xs: 12, sm: field === "location" ? 12 : 6 }}>
                      <TextField
                        label={label}
                        fullWidth
                        value={values[field]}
                        onChange={setField(field)}
                        placeholder={placeholder}
                        inputProps={{ maxLength }}
                      />
                    </Grid>
                  ))}
                </Grid>
                <TextField
                  label={t("cameraForm.streamSource")}
                  required
                  fullWidth
                  value={values.rtsp_url}
                  onChange={setField("rtsp_url")}
                  error={Boolean(errors.rtsp_url)}
                  helperText={
                    errors.rtsp_url ||
                    t("cameraForm.rtspUserPassHost554")
                  }
                />
                <TextField
                  select
                  label={t("cameraForm.detectionStrategy")}
                  fullWidth
                  value={values.strategy}
                  onChange={setField("strategy")}
                  helperText={
                    values.strategy === STRATEGY.ZONE_BASED
                      ? t("cameraForm.detectsObstaclesAndMeasuresWhat")
                      : t("cameraForm.comparesTheVisibleDoorAgainst")
                  }
                >
                  <MenuItem value={STRATEGY.ZONE_BASED}>{t("cameraForm.zoneBased")}</MenuItem>
                  <MenuItem value={STRATEGY.DOOR_CENTRIC}>{t("cameraForm.doorCentric")}</MenuItem>
                </TextField>
                <FormControlLabel
                  control={<Switch checked={values.enabled} onChange={setField("enabled")} />}
                  label={t("cameraForm.enabled")}
                />
                <Typography variant="caption" color="text.secondary" sx={{ mt: -1.5 }}>
                  {t("cameraForm.enabledCamerasStartTheirWorker")}
                </Typography>
              </Stack>
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, md: 5 }}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2">{t("cameraForm.perCameraOverrides")}</Typography>
              <Typography variant="caption" color="text.secondary">
                {t("cameraForm.leaveAFieldEmptyTo")}
              </Typography>
              <Divider sx={{ my: 2 }} />
              <Stack spacing={2.5}>
                <TextField
                  label={t("cameraForm.clearThreshold")}
                  type="number"
                  fullWidth
                  value={values.clear_min_pct}
                  onChange={setField("clear_min_pct")}
                  error={Boolean(errors.clear_min_pct)}
                  helperText={errors.clear_min_pct || t("cameraForm.atOrAboveThisAccessible")}
                  slotProps={{
                    input: { endAdornment: <InputAdornment position="end">%</InputAdornment> },
                  }}
                />
                <TextField
                  label={t("cameraForm.fullThreshold")}
                  type="number"
                  fullWidth
                  value={values.full_max_pct}
                  onChange={setField("full_max_pct")}
                  error={Boolean(errors.full_max_pct)}
                  helperText={errors.full_max_pct || t("cameraForm.belowThisAccessibleTheExit")}
                  slotProps={{
                    input: { endAdornment: <InputAdornment position="end">%</InputAdornment> },
                  }}
                />
                <TextField
                  label={t("cameraForm.confirmSeconds")}
                  type="number"
                  fullWidth
                  value={values.confirm_seconds}
                  onChange={setField("confirm_seconds")}
                  error={Boolean(errors.confirm_seconds)}
                  helperText={
                    errors.confirm_seconds ||
                    t("cameraForm.howLongAnObstructionMust")
                  }
                />
                <TextField
                  label={t("cameraForm.clearSeconds")}
                  type="number"
                  fullWidth
                  value={values.clear_seconds}
                  onChange={setField("clear_seconds")}
                  error={Boolean(errors.clear_seconds)}
                  helperText={errors.clear_seconds || t("cameraForm.howLongItMustStay")}
                />
                <TextField
                  label={t("cameraForm.processFps")}
                  type="number"
                  fullWidth
                  value={values.process_fps}
                  onChange={setField("process_fps")}
                  error={Boolean(errors.process_fps)}
                  helperText={
                    errors.process_fps ||
                    t("cameraForm.framesAnalysedPerSecondNot")
                  }
                />
              </Stack>
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {values.strategy === STRATEGY.DOOR_CENTRIC && (
        <Alert severity="info" sx={{ mt: 2 }}>
          {t("cameraForm.doorCentricNeedsDoorOnly")}
        </Alert>
      )}

      <Stack direction="row" spacing={1.5} sx={{ mt: 3 }}>
        <Button type="submit" variant="contained" size="large" disabled={saving}>
          {saving ? t("cameraForm.saving") : isEdit ? t("cameraForm.saveChanges") : t("cameraForm.createExit")}
        </Button>
        <Button component={RouterLink} to="/cameras" color="inherit" size="large">
          {t("cameraForm.cancel")}
        </Button>
      </Stack>
    </Box>
  );
}
