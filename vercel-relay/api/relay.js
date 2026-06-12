import { requireBearer, sendJson } from "../lib/auth.js";
import { readJson } from "../lib/body.js";
import { completeJob, enqueueJob, getJob, storeMode, takeNextJob } from "../lib/store.js";

function routeOf(req) {
  const url = new URL(req.url, "https://relay.local");
  return url.searchParams.get("route") || "";
}

async function createJob(req, res) {
  const auth = requireBearer(req, "RELAY_TOKEN");
  if (!auth.ok) return sendJson(res, auth.status, { ok: false, error: auth.error });
  if (req.method === "POST") {
    const job = await enqueueJob(await readJson(req));
    return sendJson(res, 200, {
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
}

async function nextJob(req, res) {
  const auth = requireBearer(req, "WORKER_TOKEN");
  if (!auth.ok) return sendJson(res, auth.status, { ok: false, error: auth.error });
  if (req.method !== "GET") return sendJson(res, 405, { ok: false, error: "method not allowed" });
  return sendJson(res, 200, { ok: true, job: await takeNextJob(), store: storeMode() });
}

async function finishJob(req, res) {
  const auth = requireBearer(req, "WORKER_TOKEN");
  if (!auth.ok) return sendJson(res, auth.status, { ok: false, error: auth.error });
  if (req.method !== "POST") return sendJson(res, 405, { ok: false, error: "method not allowed" });
  return sendJson(res, 200, { ok: true, job: await completeJob(await readJson(req)), store: storeMode() });
}

export default async function handler(req, res) {
  try {
    const route = routeOf(req);
    if (route === "jobs") return await createJob(req, res);
    if (route === "next") return await nextJob(req, res);
    if (route === "complete") return await finishJob(req, res);
    return sendJson(res, 404, { ok: false, error: "not found" });
  } catch (error) {
    return sendJson(res, 500, { ok: false, error: error.message });
  }
}
