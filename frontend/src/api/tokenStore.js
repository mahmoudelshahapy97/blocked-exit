/**
 * Where the session actually lives, outside React.
 *
 * The access token is memory-only: never localStorage, never sessionStorage,
 * so it cannot be lifted by a stray XSS reading storage or by another tab.
 * The refresh token is far more sensitive (long-lived, can mint new access
 * tokens indefinitely) but has to survive a reload to avoid forcing a login
 * on every tab close, so it goes in localStorage as the lesser evil.
 *
 * A plain module rather than a React context: the axios client (client.js)
 * needs to read/write tokens from its interceptors, which run outside any
 * component and would otherwise need to reach into React state imperatively.
 * AuthContext.jsx wraps this module for components that want to *react* to
 * login/logout.
 */

const REFRESH_KEY = "blocked-exit:refresh-token";
// Left by builds that kept the active workspace in the browser; the server
// owns it now (POST /workspaces/{id}/activate). Removed on sign-out.
const LEGACY_WORKSPACE_KEY = "blocked-exit:workspace-id";

let accessToken = null;
let currentUser = null;
const listeners = new Set();

function notify() {
  for (const fn of listeners) fn();
}

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getAccessToken() {
  return accessToken;
}

export function getUser() {
  return currentUser;
}

export function getStoredRefreshToken() {
  try {
    return localStorage.getItem(REFRESH_KEY);
  } catch {
    // Private browsing / storage disabled: sessions just don't survive a reload.
    return null;
  }
}

/** Called after login, signup and refresh. */
export function setSession({ accessToken: access, refreshToken, user }) {
  accessToken = access ?? accessToken;
  if (user !== undefined) currentUser = user;
  if (refreshToken) {
    try {
      localStorage.setItem(REFRESH_KEY, refreshToken);
    } catch {
      // See getStoredRefreshToken — storage may simply be unavailable.
    }
  }
  notify();
}

export function clearSession() {
  accessToken = null;
  currentUser = null;
  try {
    localStorage.removeItem(REFRESH_KEY);
    localStorage.removeItem(LEGACY_WORKSPACE_KEY);
  } catch {
    /* nothing to clean up if storage never worked */
  }
  notify();
}

export function isAuthenticated() {
  return Boolean(accessToken || getStoredRefreshToken());
}
