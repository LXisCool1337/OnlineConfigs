// Talking to the portal server. An access token (only needed when the portal is exposed on a
// network) is taken from ?token=… once and kept for the browser session.

const auth = { token: null };

export function initToken() {
  try {
    const params = new URLSearchParams(location.search);
    const token = params.get("token") || sessionStorage.getItem("portal_token");
    if (token) {
      auth.token = token;
      sessionStorage.setItem("portal_token", token);
    }
  } catch (_) { /* storage unavailable */ }
}

export function withToken(url) {
  if (!auth.token) return url;
  const [base, hash] = url.split("#");
  const joined = base + (base.includes("?") ? "&" : "?") + "token=" + encodeURIComponent(auth.token);
  return hash ? joined + "#" + hash : joined;
}

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

export async function api(method, path, body) {
  const options = { method, headers: {} };
  if (auth.token) options.headers.Authorization = "Bearer " + auth.token;
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let res;
  try {
    res = await fetch(path, options);
  } catch (err) {
    throw new ApiError(err.message, 0);
  }
  let data = null;
  try {
    data = await res.json();
  } catch (_) { /* empty body */ }
  if (!res.ok) throw new ApiError((data && data.error) || res.statusText, res.status);
  return data;
}
