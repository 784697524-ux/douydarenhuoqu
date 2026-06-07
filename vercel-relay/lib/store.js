import { get as blobGet, put as blobPut } from "@vercel/blob";
import { Redis } from "@upstash/redis";
import crypto from "node:crypto";

const memory = globalThis.__DOUYIN_TALENT_RELAY__ || { queue: [], jobs: new Map() };
globalThis.__DOUYIN_TALENT_RELAY__ = memory;

function redisConfig() {
  const url = process.env.KV_REST_API_URL || process.env.UPSTASH_REDIS_REST_URL;
  const token = process.env.KV_REST_API_TOKEN || process.env.UPSTASH_REDIS_REST_TOKEN;
  if (!url || !token) return null;
  return { url, token };
}

function redis() {
  const config = redisConfig();
  return config ? new Redis(config) : null;
}

function blobEnabled() {
  return Boolean(process.env.BLOB_READ_WRITE_TOKEN || (process.env.VERCEL_OIDC_TOKEN && process.env.BLOB_STORE_ID));
}

function prefix() {
  return process.env.RELAY_QUEUE_PREFIX || "douyin-talent-relay";
}

function queueKey() {
  return `${prefix()}:queue`;
}

function jobKey(id) {
  return `${prefix()}:job:${id}`;
}

function blobStatePath() {
  return `${prefix()}/state.json`;
}

function nowIso() {
  return new Date().toISOString();
}

function makeId() {
  return `${Date.now().toString(36)}-${crypto.randomBytes(6).toString("hex")}`;
}

function normalizeJob(input) {
  const taskId = String(input.task_id || input["任务编号"] || input["任务ID"] || "").trim();
  if (!taskId) throw new Error("missing task_id/任务编号");
  const id = input.request_id ? String(input.request_id) : makeId();
  const createdAt = nowIso();
  return {
    id,
    status: "queued",
    task_id: taskId,
    payload: input,
    created_at: createdAt,
    updated_at: createdAt
  };
}

function toRedisRecord(job) {
  return {
    id: job.id,
    status: job.status,
    task_id: job.task_id,
    payload: JSON.stringify(job.payload || {}),
    result: job.result ? JSON.stringify(job.result) : "",
    error: job.error || "",
    created_at: job.created_at || "",
    updated_at: job.updated_at || "",
    started_at: job.started_at || "",
    completed_at: job.completed_at || ""
  };
}

function fromRedisRecord(record) {
  if (!record) return null;
  return {
    id: record.id,
    status: record.status,
    task_id: record.task_id,
    payload: record.payload ? JSON.parse(record.payload) : {},
    result: record.result ? JSON.parse(record.result) : null,
    error: record.error || "",
    created_at: record.created_at || "",
    updated_at: record.updated_at || "",
    started_at: record.started_at || "",
    completed_at: record.completed_at || ""
  };
}

function emptyBlobState() {
  return { queue: [], jobs: {} };
}

async function readBlobState() {
  const result = await blobGet(blobStatePath(), { access: "private", useCache: false });
  if (!result) return emptyBlobState();
  const text = await new Response(result.stream).text();
  if (!text.trim()) return emptyBlobState();
  const state = JSON.parse(text);
  return {
    queue: Array.isArray(state.queue) ? state.queue : [],
    jobs: state.jobs && typeof state.jobs === "object" ? state.jobs : {}
  };
}

async function writeBlobState(state) {
  await blobPut(blobStatePath(), JSON.stringify(state), {
    access: "private",
    allowOverwrite: true,
    contentType: "application/json",
    cacheControlMaxAge: 60
  });
}

export function storeMode() {
  if (redisConfig()) return "redis";
  if (blobEnabled()) return "blob";
  return "memory";
}

export async function enqueueJob(input) {
  const job = normalizeJob(input);
  const client = redis();
  if (client) {
    await client.hset(jobKey(job.id), toRedisRecord(job));
    await client.lpush(queueKey(), job.id);
    return job;
  }
  if (blobEnabled()) {
    const state = await readBlobState();
    state.jobs[job.id] = job;
    state.queue.unshift(job.id);
    await writeBlobState(state);
    return job;
  }
  memory.jobs.set(job.id, job);
  memory.queue.unshift(job.id);
  return job;
}

export async function getJob(id) {
  const client = redis();
  if (client) return fromRedisRecord(await client.hgetall(jobKey(id)));
  if (blobEnabled()) {
    const state = await readBlobState();
    return state.jobs[id] || null;
  }
  return memory.jobs.get(id) || null;
}

export async function takeNextJob() {
  const client = redis();
  if (client) {
    const id = await client.rpop(queueKey());
    if (!id) return null;
    const existing = fromRedisRecord(await client.hgetall(jobKey(id)));
    if (!existing) return null;
    const running = { ...existing, status: "running", started_at: nowIso(), updated_at: nowIso() };
    await client.hset(jobKey(id), toRedisRecord(running));
    return running;
  }
  if (blobEnabled()) {
    const state = await readBlobState();
    const id = state.queue.pop();
    if (!id) return null;
    const existing = state.jobs[id];
    if (!existing) return null;
    const running = { ...existing, status: "running", started_at: nowIso(), updated_at: nowIso() };
    state.jobs[id] = running;
    await writeBlobState(state);
    return running;
  }

  const id = memory.queue.pop();
  if (!id) return null;
  const job = memory.jobs.get(id);
  if (!job) return null;
  job.status = "running";
  job.started_at = nowIso();
  job.updated_at = nowIso();
  memory.jobs.set(id, job);
  return job;
}

export async function completeJob(input) {
  const id = String(input.job_id || input.id || "").trim();
  if (!id) throw new Error("missing job_id");
  const existing = await getJob(id);
  if (!existing) throw new Error("job not found");
  const completed = {
    ...existing,
    status: input.ok === false ? "failed" : "completed",
    result: input.result || null,
    error: input.error || "",
    completed_at: nowIso(),
    updated_at: nowIso()
  };
  const client = redis();
  if (client) await client.hset(jobKey(id), toRedisRecord(completed));
  else if (blobEnabled()) {
    const state = await readBlobState();
    state.jobs[id] = completed;
    await writeBlobState(state);
  }
  else memory.jobs.set(id, completed);
  return completed;
}
