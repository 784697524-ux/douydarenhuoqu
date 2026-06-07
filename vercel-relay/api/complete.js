import { requireBearer, sendJson } from "../lib/auth.js";
import { readJson } from "../lib/body.js";
import { completeJob, storeMode } from "../lib/store.js";

export default async function handler(req, res) {
  const auth = requireBearer(req, "WORKER_TOKEN");
  if (!auth.ok) return sendJson(res, auth.status, { ok: false, error: auth.error });
  if (req.method !== "POST") return sendJson(res, 405, { ok: false, error: "method not allowed" });

  try {
    const body = await readJson(req);
    const job = await completeJob(body);
    return sendJson(res, 200, { ok: true, job, store: storeMode() });
  } catch (error) {
    return sendJson(res, 500, { ok: false, error: error.message });
  }
}
