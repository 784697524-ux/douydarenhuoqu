import { requireBearer, sendJson } from "../lib/auth.js";
import { readJson } from "../lib/body.js";
import { enqueueJob, getJob, storeMode } from "../lib/store.js";

export default async function handler(req, res) {
  const auth = requireBearer(req, "RELAY_TOKEN");
  if (!auth.ok) return sendJson(res, auth.status, { ok: false, error: auth.error });

  try {
    if (req.method === "POST") {
      const body = await readJson(req);
      const job = await enqueueJob(body);
      return sendJson(res, 202, {
        ok: true,
        status: "queued",
        job_id: job.id,
        task_id: job.task_id,
        store: storeMode()
      });
    }

    if (req.method === "GET") {
      const url = new URL(req.url, "https://relay.local");
      const id = url.searchParams.get("id");
      if (!id) return sendJson(res, 400, { ok: false, error: "missing id" });
      const job = await getJob(id);
      return sendJson(res, job ? 200 : 404, { ok: Boolean(job), job, store: storeMode() });
    }

    return sendJson(res, 405, { ok: false, error: "method not allowed" });
  } catch (error) {
    return sendJson(res, 500, { ok: false, error: error.message });
  }
}
