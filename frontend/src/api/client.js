import axios from "axios";
import {
  clearSession,
  getAccessToken,
  getStoredRefreshToken,
  setSession,
} from "./tokenStore";
import i18n from "i18next";

/**
 * Relative baseURL on purpose: the Vite proxy (dev) or whatever serves the
 * built bundle (prod) forwards /api to FastAPI, so the browser never makes a
 * cross-origin request and no CORS negotiation is involved.
 */
export const API_BASE = import.meta.env.VITE_API_BASE || "/api/v1";

export const client = axios.create({
  baseURL: API_BASE,
  timeout: 20000,
  headers: {
    "Content-Type": "application/json",
  },
});

// A bare axios instance, deliberately outside `client`: refreshing through
// `client` would re-enter the response interceptor below and, on a dead
// refresh token, retry itself forever.
const refreshClient = axios.create({ baseURL: API_BASE, timeout: 20000 });

client.interceptors.request.use((config) => {
  const token = getAccessToken();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  // No workspace header: the active workspace is stored server-side per user,
  // so every tab (and every <img> fetch) acts in the same one.
  return config;
});

/**
 * Ten components polling in parallel must not turn one expired access token
 * into ten refresh calls — the first 401 starts the refresh, and every other
 * 401 that arrives while it is in flight awaits the same promise.
 */
let refreshPromise = null;

const TOKEN_ROUTES = [
  "/auth/login",
  "/auth/signup",
  "/auth/refresh",
  "/auth/logout",
  "/auth/bootstrap",
  "/auth/forgot-password",
  "/auth/reset-password",
];

export async function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = (async () => {
      const refreshToken = getStoredRefreshToken();
      if (!refreshToken) throw new Error("No refresh token available");
      const { data } = await refreshClient.post("/auth/refresh", { refresh_token: refreshToken });
      setSession({ accessToken: data.access_token, refreshToken: data.refresh_token });
      return data.access_token;
    })().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

client.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error;
    // Only the endpoints that issue or end tokens are exempt. /auth/me is a
    // normal authenticated call -- it is how a reloaded tab, whose in-memory
    // access token is gone, resumes the session from the refresh token.
    const isAuthRoute = TOKEN_ROUTES.some((route) => config?.url?.startsWith(route));

    // Only ever retry once: config._retried stops a second 401 from the
    // retried request itself looping back through here forever.
    if (response?.status === 401 && !isAuthRoute && config && !config._retried) {
      config._retried = true;
      try {
        const accessToken = await refreshAccessToken();
        config.headers.Authorization = `Bearer ${accessToken}`;
        return client(config);
      } catch {
        clearSession();
        if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
          window.location.assign("/login");
        }
      }
    }
    return Promise.reject(error);
  }
);

/**
 * FastAPI answers with three different error shapes, and an operator staring
 * at a red banner needs the sentence, not the envelope:
 *   - app errors  -> { error, message, details }
 *   - validation  -> { detail: [{ loc, msg }, ...] }
 *   - HTTPException -> { detail: "..." }
 */
export function errorMessage(error) {
  if (axios.isCancel?.(error) || error?.code === "ERR_CANCELED") return null;

  const data = error?.response?.data;
  if (data) {
    if (typeof data === "string") return data;
    if (data.message) return data.message;
    if (typeof data.detail === "string") return data.detail;
    if (Array.isArray(data.detail)) {
      return data.detail
        .map((d) => {
          // loc is ["body", "door_polygon", 0] — the first entry is the
          // request part, which tells the operator nothing.
          const field = Array.isArray(d.loc) ? d.loc.slice(1).join(".") : "";
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
  }
  if (error?.code === "ECONNABORTED") return i18n.t("common:errors.timeout");
  if (error?.message === "Network Error") {
    return i18n.t("common:errors.network");
  }
  return error?.message || i18n.t("common:errors.generic");
}

export function mediaUrl(path, params = {}) {
  const qs = new URLSearchParams(params).toString();
  return `${API_BASE}${path}${qs ? `?${qs}` : ""}`;
}

/**
 * Fetch an image endpoint as an object URL, carrying auth headers along.
 * The caller owns the returned URL and must revokeObjectURL it, or every
 * polled frame leaks a blob for the lifetime of the document.
 */
export async function fetchImageObjectUrl(path, { params, signal } = {}) {
  const response = await client.get(path, {
    params,
    signal,
    responseType: "blob",
  });
  return URL.createObjectURL(response.data);
}

export default client;
