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

/**
 * Draw the exit region the zone-based strategy measures against.
 *
 * The polygon is stored normalized to [0,1] so it survives a camera being
 * swapped for one with a different sensor. This page never does that division
 * itself: it sends pixel points plus the frame size they were drawn on and
 * lets the backend normalize, which keeps one implementation of that maths.
 */
export default function ZoneEditor() {
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
      toast.success("Fresh frame captured");
      setLoadError(null);
    } catch (err) {
      toast.error(errorMessage(err));
    } finally {
      setCapturing(false);
    }
  };

  const save = async () => {
    if (points.length < 3) {
      toast.warning("An exit region needs at least 3 points.");
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
      toast.success("Exit region saved — the worker picked it up immediately.");
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

  if (loading) return <Loading label="Grabbing a frame from the camera…" height={340} />;

  return (
    <Box>
      <PageHeader
        title={`Exit region — ${camera?.name || `camera ${cameraId}`}`}
        subtitle="Trace the doorway. Everything overlapping this shape counts against how accessible the exit is."
        actions={
          <>
            <Button
              startIcon={<ArrowBackIcon />}
              component={RouterLink}
              to={`/cameras/${cameraId}`}
              color="inherit"
            >
              Back
            </Button>
            <Button
              startIcon={<CameraAltIcon />}
              onClick={regrabFrame}
              disabled={capturing}
              color="inherit"
            >
              New frame
            </Button>
            <Button
              startIcon={<SaveIcon />}
              variant="contained"
              onClick={save}
              disabled={saving || points.length < 3}
            >
              {saving ? "Saving…" : "Save region"}
            </Button>
          </>
        }
      />

      <ErrorState
        error={loadError}
        onRetry={load}
        title="Could not grab a frame"
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
                Region
              </Typography>
              <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 2 }}>
                <Chip
                  size="small"
                  color={points.length >= 3 ? "success" : "warning"}
                  label={`${points.length} point${points.length === 1 ? "" : "s"}`}
                />
                {points.length > 0 && points.length < 3 && (
                  <Typography variant="caption" color="warning.main">
                    at least 3 needed
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
                  Undo
                </Button>
                <Button
                  size="small"
                  startIcon={<ClearIcon />}
                  onClick={() => updatePoints([])}
                  disabled={!points.length}
                  color="inherit"
                >
                  Clear
                </Button>
              </Stack>

              <Divider sx={{ my: 2 }} />

              <Typography variant="caption" color="text.secondary" component="div">
                Saved points are normalized to [0, 1], so the region keeps its meaning if
                this camera is later replaced with one of a different resolution.
              </Typography>

              {camera?.strategy === STRATEGY.DOOR_CENTRIC && (
                <>
                  <Divider sx={{ my: 2 }} />
                  <Typography variant="subtitle2" gutterBottom>
                    Door-centric reference
                  </Typography>
                  <Typography variant="caption" color="text.secondary" display="block" sx={{ mb: 1.5 }}>
                    Capture this while the exit is completely clear. Every later frame is
                    measured against it.
                  </Typography>
                  <Button
                    size="small"
                    variant="outlined"
                    startIcon={<PhotoCameraIcon />}
                    onClick={captureReference}
                    disabled={capturing}
                    fullWidth
                  >
                    {capturing ? "Capturing…" : "Capture reference now"}
                  </Button>
                  {camera?.reference_bbox && (
                    <Alert severity="success" sx={{ mt: 1.5 }} icon={false}>
                      <Typography variant="caption">
                        Reference stored: [
                        {camera.reference_bbox.map((v) => Number(v).toFixed(3)).join(", ")}]
                      </Typography>
                    </Alert>
                  )}
                </>
              )}

              {camera?.strategy === STRATEGY.ZONE_BASED && !camera?.door_polygon?.length && (
                <Alert severity="warning" sx={{ mt: 2 }}>
                  This camera has no saved region yet. Zone-based detection has nothing to
                  measure until one is drawn.
                </Alert>
              )}
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  );
}
