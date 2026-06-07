import assert from "node:assert/strict";
import { enqueueJob, takeNextJob, completeJob, getJob, storeMode } from "../lib/store.js";

const job = await enqueueJob({ task_id: "008", smoke: true, wait_ready: 5 });
assert.equal(job.task_id, "008");

const next = await takeNextJob();
assert.equal(next.id, job.id);
assert.equal(next.status, "running");
assert.equal(next.payload.smoke, true);

const done = await completeJob({ job_id: job.id, ok: true, result: { opened_contacts: 0 } });
assert.equal(done.status, "completed");

const loaded = await getJob(job.id);
assert.equal(loaded.result.opened_contacts, 0);
console.log(JSON.stringify({ ok: true, store: storeMode(), job_id: job.id }));
