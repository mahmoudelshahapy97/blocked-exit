import client, { fetchImageObjectUrl, mediaUrl } from "./client";

/** One function per backend route, so no component builds a URL by hand. */

// --- health ---------------------------------------------------------------
export const health = {
  live: () => client.get("/health").then((r) => r.data),
  ready: () => client.get("/health/ready").then((r) => r.data),
};

// --- auth -------------------------------------------------------------------
export const auth = {
  bootstrap: (opts) => client.get("/auth/bootstrap", opts).then((r) => r.data),
  signup: (payload) => client.post("/auth/signup", payload).then((r) => r.data),
  login: (payload) => client.post("/auth/login", payload).then((r) => r.data),
  refresh: (refreshToken) =>
    client.post("/auth/refresh", { refresh_token: refreshToken }).then((r) => r.data),
  logout: (refreshToken) =>
    client.post("/auth/logout", refreshToken ? { refresh_token: refreshToken } : {}),
  me: (opts) => client.get("/auth/me", opts).then((r) => r.data),
  updateMe: (payload) => client.patch("/auth/me", payload).then((r) => r.data),
  changePassword: (payload) => client.post("/auth/me/password", payload),

  // Superadmin only.
  listUsers: (opts) => client.get("/auth/users", opts).then((r) => r.data),
  createUser: (payload) => client.post("/auth/users", payload).then((r) => r.data),
  updateUser: (userId, payload) =>
    client.patch(`/auth/users/${userId}`, payload).then((r) => r.data),
};

// --- workspaces -------------------------------------------------------------
export const workspaces = {
  list: (params, opts) => client.get("/workspaces", { params, ...opts }).then((r) => r.data),
  active: (opts) => client.get("/workspaces/active", opts).then((r) => r.data),
  permissions: (opts) => client.get("/workspaces/active/permissions", opts).then((r) => r.data),
  activate: (id) => client.post(`/workspaces/${id}/activate`).then((r) => r.data),
  get: (id, opts) => client.get(`/workspaces/${id}`, opts).then((r) => r.data),
  cameras: (id, opts) => client.get(`/workspaces/${id}/cameras`, opts).then((r) => r.data),
  members: (id, opts) => client.get(`/workspaces/${id}/members`, opts).then((r) => r.data),

  // Superadmin only.
  create: (payload) => client.post("/workspaces", payload).then((r) => r.data),
  update: (id, payload) => client.patch(`/workspaces/${id}`, payload).then((r) => r.data),
  deactivate: (id) => client.post(`/workspaces/${id}/deactivate`).then((r) => r.data),
  remove: (id) => client.delete(`/workspaces/${id}`),
  addMember: (id, payload) =>
    client.post(`/workspaces/${id}/members`, payload).then((r) => r.data),
  updateMember: (id, memberId, role) =>
    client.patch(`/workspaces/${id}/members/${memberId}`, { role }).then((r) => r.data),
  removeMember: (id, memberId) => client.delete(`/workspaces/${id}/members/${memberId}`),
};

// --- cameras --------------------------------------------------------------
export const cameras = {
  list: (params) => client.get("/cameras", { params }).then((r) => r.data),
  get: (id, opts) => client.get(`/cameras/${id}`, opts).then((r) => r.data),
  create: (payload) => client.post("/cameras", payload).then((r) => r.data),
  update: (id, payload) => client.patch(`/cameras/${id}`, payload).then((r) => r.data),
  remove: (id) => client.delete(`/cameras/${id}`).then((r) => r.data),
  /** Distinct location/area/building/floor/zone values, narrowed by `params`. */
  hierarchy: (params, opts) =>
    client.get("/cameras/hierarchy", { params, ...opts }).then((r) => r.data),
  probe: (id) => client.post(`/cameras/${id}/probe`).then((r) => r.data),
  probeAll: () => client.post("/cameras/probe-all").then((r) => r.data),

  /**
   * A clean frame plus the pixel size it was captured at. The size is the
   * point: the polygon editor draws in those pixels and sends them back with
   * frame_width/frame_height so the server normalizes to [0,1] itself.
   */
  calibrationFrame: async (id, { signal } = {}) => {
    const response = await client.get(`/cameras/${id}/calibration-frame`, {
      responseType: "blob",
      signal,
    });
    return {
      objectUrl: URL.createObjectURL(response.data),
      width: Number(response.headers["x-frame-width"]) || 0,
      height: Number(response.headers["x-frame-height"]) || 0,
    };
  },

  polygonPreviewUrl: (id) =>
    mediaUrl(`/cameras/${id}/door-polygon/preview`, { t: Date.now() }),

  polygonPreview: (id, opts) =>
    fetchImageObjectUrl(`/cameras/${id}/door-polygon/preview`, {
      params: { t: Date.now() },
      ...opts,
    }),

  setDoorPolygon: (id, { doorPolygon, frameWidth, frameHeight }) =>
    client
      .put(`/cameras/${id}/door-polygon`, {
        door_polygon: doorPolygon,
        // Omitted entirely when absent: the backend rejects one without the
        // other, and treats points as already-normalized when neither is sent.
        ...(frameWidth && frameHeight
          ? { frame_width: frameWidth, frame_height: frameHeight }
          : {}),
      })
      .then((r) => r.data),

  captureReference: (id) => client.post(`/cameras/${id}/reference`).then((r) => r.data),
};

// --- monitoring -----------------------------------------------------------
export const monitoring = {
  statusAll: (opts) => client.get("/monitoring/status", opts).then((r) => r.data),
  status: (id, opts) => client.get(`/monitoring/${id}/status`, opts).then((r) => r.data),
  start: (id) => client.post(`/monitoring/${id}/start`).then((r) => r.data),
  stop: (id) => client.post(`/monitoring/${id}/stop`).then((r) => r.data),
  restart: (id) => client.post(`/monitoring/${id}/restart`).then((r) => r.data),

  /**
   * MJPEG endpoint for <img src>. An <img> tag cannot send an Authorization
   * header, so this mints a 60-second, single-camera ticket first (a normal
   * bearer-authenticated call) and puts *that* on the URL instead of the real
   * access token — a leaked ticket costs one minute of one camera, not the
   * account. Callers must re-fetch before the ticket expires for a
   * long-running <img>; LiveView does this on an interval.
   */
  streamUrl: async (id) => {
    const ticket = await client
      .post(`/monitoring/${id}/stream-ticket`)
      .then((r) => r.data);
    return mediaUrl(`/monitoring/${id}/stream`, { ticket: ticket.ticket });
  },

  snapshot: (id, { annotated = true, signal } = {}) =>
    fetchImageObjectUrl(`/monitoring/${id}/snapshot`, {
      params: { annotated, t: Date.now() },
      signal,
    }),
};

// --- events ---------------------------------------------------------------
export const events = {
  list: (params, opts) => client.get("/events", { params, ...opts }).then((r) => r.data),
  get: (id) => client.get(`/events/${id}`).then((r) => r.data),
  overview: (opts) => client.get("/events/overview", opts).then((r) => r.data),
  /** Object URL of the event's snapshot; the caller revokes it. */
  snapshot: (id, opts) => fetchImageObjectUrl(`/events/${id}/snapshot`, opts),
  // Members and up.
  acknowledge: (id, note) =>
    client.post(`/events/${id}/acknowledge`, { note: note || undefined }).then((r) => r.data),
  resolve: (id, note) =>
    client
      .post(`/events/${id}/resolve`, { status: "resolved", note: note || undefined })
      .then((r) => r.data),
  // Workspace admins only. `remove` needs at least one filter.
  remove: (params) => client.delete("/events", { params }).then((r) => r.data),
  removeAll: () =>
    client.delete("/events/all", { params: { confirm: true } }).then((r) => r.data),
};

// --- alerts ---------------------------------------------------------------
export const alerts = {
  list: (params, opts) => client.get("/alerts", { params, ...opts }).then((r) => r.data),
  acknowledge: (id, acknowledgedBy) =>
    client.post(`/alerts/${id}/ack`, { acknowledged_by: acknowledgedBy }).then((r) => r.data),
  test: (cameraId, channels) =>
    client
      .post("/alerts/test", {
        camera_id: cameraId,
        ...(channels?.length ? { channels } : {}),
      })
      .then((r) => r.data),
};

// --- analytics ------------------------------------------------------------
export const analytics = {
  summary: (days = 7, opts, filters = {}) =>
    client
      .get("/analytics/summary", { params: { days, ...filters }, ...opts })
      .then((r) => r.data),
  mostBlocked: (days = 7, limit = 10, opts) =>
    client
      .get("/analytics/most-blocked", { params: { days, limit }, ...opts })
      .then((r) => r.data),
  dailyReport: (reportDate, opts, filters = {}) =>
    client
      .get("/analytics/daily-report", {
        params: { ...filters, ...(reportDate ? { report_date: reportDate } : {}) },
        ...opts,
      })
      .then((r) => r.data),
  // The platform's charts; `filters` is the EventFilterBar value.
  incidentsPerCamera: (filters, opts) =>
    client.get("/analytics/incidents-per-camera", { params: filters, ...opts }).then((r) => r.data),
  confidenceAudit: (filters, opts) =>
    client.get("/analytics/confidence-audit", { params: filters, ...opts }).then((r) => r.data),
  trend: (filters, bucket, opts) =>
    client
      .get("/analytics/trend", { params: { ...filters, ...(bucket ? { bucket } : {}) }, ...opts })
      .then((r) => r.data),
  heatmap: (filters, opts) =>
    client.get("/analytics/heatmap", { params: filters, ...opts }).then((r) => r.data),
  responseTimes: (filters, opts) =>
    client.get("/analytics/response-times", { params: filters, ...opts }).then((r) => r.data),
  breakdown: (filters, opts) =>
    client.get("/analytics/breakdown", { params: filters, ...opts }).then((r) => r.data),
  timeline: (cameraId, days = 7, limit = 200, opts) =>
    client
      .get(`/analytics/${cameraId}/timeline`, { params: { days, limit }, ...opts })
      .then((r) => r.data),
};

export default { health, auth, workspaces, cameras, monitoring, events, alerts, analytics };
