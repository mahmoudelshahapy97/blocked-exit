import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

/**
 * Dev server proxies every backend path so the browser only ever talks to the
 * Vite origin. Two things fall out of that, and both matter here:
 *
 *  - No CORS. The backend defaults to CORS_ORIGINS=* which browsers refuse to
 *    pair with credentials, so a same-origin proxy sidesteps the whole problem.
 *  - MJPEG works. <img src="/api/v1/monitoring/1/stream"> is a same-origin
 *    request, so it is not subject to a preflight the multipart response
 *    could not answer anyway.
 *
 * The proxy target follows the backend's API_PORT (.env sets 8001, not the
 * documented 8000), overridable with VITE_API_TARGET.
 */
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const target = env.VITE_API_TARGET || "http://127.0.0.1:8001";

  // MJPEG responses never end. The default proxy timeouts would sever a live
  // view after a minute of perfectly healthy streaming, so disable both.
  const streamSafe = {
    target,
    changeOrigin: true,
    timeout: 0,
    proxyTimeout: 0,
  };

  return {
    plugins: [react()],
    server: {
      port: Number(env.VITE_PORT) || 5173,
      strictPort: false,
      open: false,
      proxy: {
        "/api": streamSafe,
        // The backend's own zone editor and Swagger UI, reachable from the
        // console without the operator needing to know the API port.
        "/ui": { target, changeOrigin: true },
        "/docs": { target, changeOrigin: true },
        "/redoc": { target, changeOrigin: true },
        "/openapi.json": { target, changeOrigin: true },
      },
    },
    preview: {
      port: Number(env.VITE_PREVIEW_PORT) || 4173,
      proxy: {
        "/api": streamSafe,
        "/ui": { target, changeOrigin: true },
        "/docs": { target, changeOrigin: true },
      },
    },
    build: {
      outDir: "dist",
      sourcemap: mode !== "production",
      chunkSizeWarningLimit: 900,
    },
  };
});
