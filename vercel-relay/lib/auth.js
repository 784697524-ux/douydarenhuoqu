export function requireBearer(req, envName, options = {}) {
  const expected = process.env[envName];
  if (!expected) {
    return { ok: false, status: 500, error: `${envName} is not configured` };
  }
  const auth = req.headers.authorization || req.headers.Authorization || "";
  if (auth === `Bearer ${expected}`) {
    return { ok: true };
  }
  if (options.allowTokenParam) {
    const url = new URL(req.url, "https://relay.local");
    const queryToken = url.searchParams.get("token") || url.searchParams.get("relay_token") || "";
    const bodyToken = options.body?.token || options.body?.relay_token || "";
    if (queryToken === expected || bodyToken === expected) {
      return { ok: true };
    }
  }
  if (auth !== `Bearer ${expected}`) {
    return { ok: false, status: 401, error: "unauthorized" };
  }
  return { ok: true };
}

export function withoutAuthFields(input) {
  const output = { ...(input || {}) };
  delete output.token;
  delete output.relay_token;
  return output;
}

export function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(payload));
}
