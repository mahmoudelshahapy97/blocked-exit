import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";

const HANDLE_RADIUS = 6;
const GRAB_RADIUS = 12;

/**
 * Trace the exit region over a still frame from the camera.
 *
 * Points are held in the frame's *native* pixel coordinates, never in the
 * pixels the canvas happens to be displayed at. That separation is what makes
 * the result independent of the operator's window size: the canvas is redrawn
 * at whatever width the layout gives it, while the saved polygon is always
 * measured against `frameWidth`/`frameHeight` — the dimensions the backend
 * reports in X-Frame-Width/X-Frame-Height and normalizes against.
 */
export function PolygonEditor({
  imageUrl,
  frameWidth,
  frameHeight,
  points,
  onChange,
  disabled = false,
}) {
  const containerRef = useRef(null);
  const canvasRef = useRef(null);
  const imageRef = useRef(null);
  const dragIndexRef = useRef(-1);

  const [imageReady, setImageReady] = useState(false);
  const [displaySize, setDisplaySize] = useState({ width: 0, height: 0 });
  const [hoverIndex, setHoverIndex] = useState(-1);

  // --- load the still frame ----------------------------------------------
  useEffect(() => {
    if (!imageUrl) {
      imageRef.current = null;
      setImageReady(false);
      return undefined;
    }
    const image = new Image();
    let cancelled = false;
    image.onload = () => {
      if (cancelled) return;
      imageRef.current = image;
      setImageReady(true);
    };
    image.onerror = () => {
      if (!cancelled) setImageReady(false);
    };
    image.src = imageUrl;
    return () => {
      cancelled = true;
    };
  }, [imageUrl]);

  const nativeWidth = frameWidth || imageRef.current?.naturalWidth || 0;
  const nativeHeight = frameHeight || imageRef.current?.naturalHeight || 0;

  // --- keep the canvas sized to its container ----------------------------
  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element || !nativeWidth || !nativeHeight) return undefined;

    const resize = () => {
      const width = element.clientWidth;
      setDisplaySize({
        width,
        height: Math.round((width * nativeHeight) / nativeWidth),
      });
    };
    resize();

    const observer = new ResizeObserver(resize);
    observer.observe(element);
    return () => observer.disconnect();
  }, [nativeWidth, nativeHeight, imageReady]);

  const scale = displaySize.width && nativeWidth ? displaySize.width / nativeWidth : 1;

  // --- drawing ------------------------------------------------------------
  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    const image = imageRef.current;
    if (!canvas || !displaySize.width) return;

    // Render at device pixel ratio: on a HiDPI screen a 1x canvas makes the
    // handles the operator is aiming at visibly soft.
    const dpr = window.devicePixelRatio || 1;
    canvas.width = displaySize.width * dpr;
    canvas.height = displaySize.height * dpr;
    canvas.style.width = displaySize.width + "px";
    canvas.style.height = displaySize.height + "px";

    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, displaySize.width, displaySize.height);

    if (image) {
      ctx.drawImage(image, 0, 0, displaySize.width, displaySize.height);
    } else {
      ctx.fillStyle = "#0b1220";
      ctx.fillRect(0, 0, displaySize.width, displaySize.height);
    }

    if (!points.length) return;

    const screen = points.map(([x, y]) => [x * scale, y * scale]);

    ctx.beginPath();
    screen.forEach(([x, y], index) => (index === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
    if (screen.length >= 3) {
      ctx.closePath();
      ctx.fillStyle = "rgba(34, 197, 94, 0.22)";
      ctx.fill();
    }
    ctx.strokeStyle = "#22c55e";
    ctx.lineWidth = 2;
    ctx.stroke();

    screen.forEach(([x, y], index) => {
      ctx.beginPath();
      ctx.arc(x, y, index === hoverIndex ? HANDLE_RADIUS + 2 : HANDLE_RADIUS, 0, Math.PI * 2);
      // The first vertex is tinted differently so the operator can tell which
      // way the outline runs when points overlap.
      ctx.fillStyle = index === 0 ? "#f97316" : "#ffffff";
      ctx.fill();
      ctx.strokeStyle = "#0b1220";
      ctx.lineWidth = 2;
      ctx.stroke();

      ctx.fillStyle = "#e2e8f0";
      ctx.font = "600 11px system-ui, sans-serif";
      ctx.fillText(String(index + 1), x + HANDLE_RADIUS + 3, y - HANDLE_RADIUS);
    });
  }, [displaySize, points, scale, hoverIndex]);

  useEffect(() => {
    draw();
  }, [draw, imageReady]);

  // --- pointer handling ---------------------------------------------------
  const toNative = useCallback(
    (event) => {
      const rect = canvasRef.current.getBoundingClientRect();
      const x = (event.clientX - rect.left) / scale;
      const y = (event.clientY - rect.top) / scale;
      // Clamp: a point dragged off the edge would fail the backend's [0,1]
      // check after normalization, which is a confusing way to learn you
      // slipped off the canvas.
      return [
        Math.max(0, Math.min(nativeWidth, x)),
        Math.max(0, Math.min(nativeHeight, y)),
      ];
    },
    [scale, nativeWidth, nativeHeight]
  );

  const findHandle = useCallback(
    (native) => {
      const threshold = GRAB_RADIUS / scale;
      let best = -1;
      let bestDistance = Infinity;
      points.forEach(([x, y], index) => {
        const distance = Math.hypot(x - native[0], y - native[1]);
        if (distance < threshold && distance < bestDistance) {
          best = index;
          bestDistance = distance;
        }
      });
      return best;
    },
    [points, scale]
  );

  const handlePointerDown = (event) => {
    if (disabled || !imageReady) return;
    if (event.button === 2 || event.ctrlKey) return; // deletion is handled on context menu

    const native = toNative(event);
    const index = findHandle(native);

    if (index >= 0) {
      dragIndexRef.current = index;
      canvasRef.current.setPointerCapture(event.pointerId);
      return;
    }
    onChange([...points, native]);
  };

  const handlePointerMove = (event) => {
    if (disabled || !imageReady) return;
    const native = toNative(event);
    const index = dragIndexRef.current;
    if (index >= 0) {
      const next = points.slice();
      next[index] = native;
      onChange(next);
      return;
    }
    setHoverIndex(findHandle(native));
  };

  const endDrag = (event) => {
    if (dragIndexRef.current >= 0) {
      canvasRef.current?.releasePointerCapture?.(event.pointerId);
      dragIndexRef.current = -1;
    }
  };

  const handleContextMenu = (event) => {
    event.preventDefault();
    if (disabled || !imageReady) return;
    const index = findHandle(toNative(event));
    if (index >= 0) onChange(points.filter((_, i) => i !== index));
  };

  return (
    <Box ref={containerRef} sx={{ width: "100%" }}>
      <Box
        component="canvas"
        ref={canvasRef}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={endDrag}
        onPointerLeave={(event) => {
          endDrag(event);
          setHoverIndex(-1);
        }}
        onContextMenu={handleContextMenu}
        sx={{
          display: "block",
          width: "100%",
          borderRadius: 2,
          bgcolor: "#05070d",
          cursor: disabled ? "not-allowed" : hoverIndex >= 0 ? "grab" : "crosshair",
          touchAction: "none",
        }}
      />
      <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: "block" }}>
        Click to add a point · drag a point to move it · right-click a point to delete it.
        At least 3 points are needed.
        {nativeWidth > 0 ? ` Frame is ${nativeWidth}x${nativeHeight}px.` : ""}
      </Typography>
    </Box>
  );
}

export default PolygonEditor;
