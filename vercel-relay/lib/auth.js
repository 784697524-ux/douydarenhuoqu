export function requireBearer(req, envName) {
  const expected = process.env[envName];
  if (!expected) {
    return { ok: false, status: 500, error: `${envName} is not configured` };
  }
  const auth = req.headers.authorization || req.headers.Authorization || "";
  if (auth !== `Bearer ${expected}`) {
    return { ok: false, status: 401, error: "unauthorized" };
  }
  return { ok: true };
}

export function sendJson(res, status, payload) {
  res.statusCode = status;
  res.setHeader("Content-Type", "application/json; charset=utf-8");
  res.end(JSON.stringify(payload));
}
