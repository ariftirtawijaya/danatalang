import axios from "axios";

export const API = `${process.env.REACT_APP_BACKEND_URL}/api`;

export const api = axios.create({ baseURL: API });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem("pk_token");
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

// Re-authentication endpoints legitimately answer 401 for a wrong current password
// while the session itself is still valid, so they must not trigger auto-logout.
const REAUTH_PATHS = ["/auth/profile", "/auth/password", "/settings/factory-reset"];

api.interceptors.response.use(
  (r) => r,
  (error) => {
    const url = error.config?.url || "";
    const isReauth = REAUTH_PATHS.some((p) => url.startsWith(p));
    if (error.response?.status === 401 && !isReauth && localStorage.getItem("pk_token")) {
      localStorage.removeItem("pk_token");
      if (!window.location.pathname.startsWith("/login")) window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export function errMsg(error) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((e) => e?.msg || JSON.stringify(e)).join(" ");
  if (detail?.msg) return detail.msg;
  return error?.message || "Terjadi kesalahan";
}
