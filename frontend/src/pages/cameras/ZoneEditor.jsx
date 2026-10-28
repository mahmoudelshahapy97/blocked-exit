import { useCallback, useEffect, useRef, useState } from "react";
import { Link as RouterLink, useNavigate, useParams } from "react-router-dom";
import Alert from "@mui/material/Alert";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Card from "@mui/material/Card";
import CardContent from "@mui/material/CardContent";
import Chip from "@mui/material/Chip";
import Divider from "@mui/material/Divider";
import Grid from "@mui/material/Grid2";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import SaveIcon from "@mui/icons-material/Save";
import UndoIcon from "@mui/icons-material/Undo";
import ClearIcon from "@mui/icons-material/LayersClear";
import CameraAltIcon from "@mui/icons-material/CameraAlt";
import PhotoCameraIcon from "@mui/icons-material/PhotoCamera";

import { errorMessage } from "../../api/client";
import { cameras as camerasApi } from "../../api/endpoints";
import { useToast } from "../../components/Toast";
import { ErrorState, Loading } from "../../components/DataStates";
import PageHeader from "../../components/PageHeader";
import PolygonEditor from "../../components/PolygonEditor";
import { STRATEGY } from "../../utils/constants";
import { useTranslation } from "react-i18next";

/**
 * Draw the exit region the zone-based strategy measures against.
 *
 * The polygon is stored normalized to [0,1] so it survives a camera being
 * swapped for one with a different sensor. This page never does that division
 * itself: it sends pixel points plus the frame size they were drawn on and
 * lets the backend normalize, which keeps one implementation of that maths.
 */
export default function ZoneEditor() {
  const { t } = useTranslation();
  const { cameraId } = useParams();
  const navigate = useNavigate();
  const toast = useToast();

  const [camera, setCamera] = useState(null);
  const [frame, setFrame] = useState(null);
  const [points, setPoints] = useState([]);
  const [history, setHistory] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [capturing, setCapturing] = useState(false);

  const objectUrlRef = useRef(null);

  const loadFrame = useCallback(
    async (cameraRecord) => {
      // Revoke before replacing: re-grabbing a frame on every click would
      // otherwise pin every previous JPEG in memory.
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
      objectUrlRef.current = null;

      const captured = await camerasApi.calibrationFrame(cameraRecord.id);
      objectUrlRef.current = captured.objectUrl;
      setFrame(captured);
      return captured;
    },
    []
  );

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const cameraRecord = await camerasApi.get(cameraId);
      setCamera(cameraRecord);

      let captured = null;
      try {
        captured = await loadFrame(cameraRecord);
      } catch (err) {
        // A dead stream must not block the page: the operator may still want
        // to see the stored polygon or read the camera's settings.
        setLoadError(errorMessage(err));
      }

      // The stored polygon is normalized; the editor works in frame pixels.
      if (cameraRecord.door_polygon?.length && captured?.width && captured?.height) {
        setPoints(
          cameraRecord.door_polygon.map(([x, y]) => [x * captured.width, y * captured.height])
        );
      } else {
        setPoints([]);
      }
      setHistory([]);
    } catch (err) {
      setLoadError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [cameraId, loadFrame]);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(
    () => () => {
      if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
    },
    []
  );

  const updatePoints = (next) => {
    setHistory((current) => [...current.slice(-49), points]);
    setPoints(next);
  };

  const undo = () => {
    setHistory((current) => {
      if (!current.length) return current;
      setPoints(current[current.length - 1]);
      return current.slice(0, -1);
    });
  };

  const regrabFrame = async () => {
    if (!camera) return;
    setCapturing(true);
    try {
      await loadFrame(camera);
      toast.success(t("zoneEditor.freshFrameCaptured"));
      setLoadError(null);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setCapturing(false);
    }
  };

  const save = async () => {
    if (points.length < 3) {
      toast.warning(t("zoneEditor.anExitRegionNeedsAt"));
      return;
    }
    setSaving(true);
    try {
      const updated = await camerasApi.setDoorPolygon(cameraId, {
        doorPolygon: points.map(([x, y]) => [Math.round(x), Math.round(y)]),
        frameWidth: frame?.width,
        frameHeight: frame?.height,
      });
      setCamera(updated);
      toast.success(t("zoneEditor.exitRegionSavedTheWorker"));
      navigate(`/cameras/${cameraId}`);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const captureReference = async () => {
    setCapturing(true);
    try {
      const result = await camerasApi.captureReference(cameraId);
      toast.success(result.message);
      setCamera((current) => ({
        ...current,
        reference_bbox: result.reference_bbox,
        reference_captured_at: result.captured_at,
      }));
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setCapturing(false);
    }
  };

  if (loading) return <Loading label={t("zoneEditor.grabbingAFrameFromThe")} height={340} />;

  return (
    <Box>
      <PageHeader
        title={t("zoneEditor.exitRegionV0", { v0: camera?.name || `camera ${cameraId}` })}
        subtitle={t("zoneEditor.traceTheDoorwayEverythingOverlapping")}
        actions={
          <>
            <Button
              startIcon={<ArrowBackIcon />}
              component={RouterLink}
              to={`/cameras/${cameraId}`}
              color="inherit"
            >
              {t("zoneEditor.back")}
            </Button>
            <Button
              startIcon={<CameraAltIcon />}
              onClick={regrabFrame}
              disabled={capturing}
              color="inherit"
            >
              {t("zoneEditor.newFrame")}
            </Button>
            <Button
              startIcon={<SaveIcon />}
              variant="contained"
              onClick={save}
              disabled={saving || points.length < 3}
            >
              {saving ? t("zoneEditor.saving") : t("zoneEditor.saveRegion")}
            </Button>
          </>
        }
      />

      <ErrorState
        error={loadError}
        onRetry={load}
        title={t("zoneEditor.couldNotGrabAFrame")}
      />

      <Grid container spacing={2}>
        <Grid size={{ xs: 12, lg: 8 }}>
          <Card>
            <CardContent>
              <PolygonEditor
                imageUrl={frame?.objectUrl}
                frameWidth={frame?.width}
                frameHeight={frame?.height}
                points={points}
                onChange={updatePoints}
                disabled={!frame}
              />
            </CardContent>
          </Card>
        </Grid>

        <Grid size={{ xs: 12, lg: 4 }}>
          <Card>
            <CardContent>
              <Typography variant="subtitle2" gutterBottom>
                {t("zoneEditor.region")}
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
                <Chip
                  size="small"
                  color={points.length >= 3 ? "success" : "warning"}
                  label={t("zoneEditor.pointCount", { count: points.length })}
                />
                {points.length > 0 && points.length < 3 && (
                  <Typography variant="caption" color="warning.main">
                    {t("zoneEditor.atLeast3Needed")}
                  </Typography>
                )}
              </Stack>

              <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
                <Button
                  size="small"
                  startIcon={<UndoIcon />}
                  onClick={undo}
                  disabled={!history.length}
                  color="inherit"
                >
                  {t("zoneEditor.undo")}
                </Button>
                <Button
                  size="small"
                  startIcon={<ClearIcon />}
                  onClick={() => updatePoints([])}
                  disabled={!points.length}
                  color="inherit"
                >
                  {t("zoneEditor.clear")}
                </Button>
              </Stack>

              <Divider sx={{ my: 2 }} />

              <Typography variant="caption" color="text.secondary" component="div">
                {t("zoneEditor.savedPointsAreNormalizedTo")}
              </Typography>

              {camera?.strategy === STRATEGY.DOOR_CENTRIC && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Typography variant="subtitle2" gutterBottom>
                    {t("zoneEditor.doorCentricReference")}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
                    {t("zoneEditor.captureThisWhileTheExit")}
                  </Typography>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<PhotoCameraIcon />}
                    onClick={captureReference}
                    disabled={capturing}
                    fullWidth
                  >
                    {capturing ? t("zoneEditor.capturing") : t("zoneEditor.captureReferenceNow")}
                  </Button>
                  {camera?.reference_bbox && (
                    <Alert severity="success" sx={{ mt: 1.5 }} icon={false}>
                      <Typography variant="caption">
                        {t("zoneEditor.referenceStoredV0", { v0: camera.reference_bbox.map((v) => Number(v).toFixed(3)).join(", ") })}
                      </Typography>
                    </Alert>
                  )}
                </>
              )}

              {camera?.strategy === STRATEGY.ZONE_BASED && !camera?.door_polygon?.length && (
                <Alert severity="warning" sx={{ mt: 2 }}>
                  {t("zoneEditor.thisCameraHasNoSaved")}
                </Alert>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
