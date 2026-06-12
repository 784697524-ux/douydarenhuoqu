# Vercel HTTPS Relay for Douyin Talent Tasks

This relay gives DingTalk AI Table automation a stable HTTPS endpoint while keeping Douyin Chrome execution on the user's local machine.

## Endpoints

- `POST /api/jobs`: DingTalk button enqueues a task.
- `GET /api/next`: local worker pulls one queued task.
- `POST /api/complete`: local worker reports execution result.
- `GET /api/jobs?id=<job_id>`: query job status.
- `GET /api/ping`: public connectivity check for DingTalk HTTP automation.

## Required Vercel environment variables

- `RELAY_TOKEN`: token used by DingTalk HTTP request.
- `WORKER_TOKEN`: token used by the local worker.

For long-term durable queue storage, connect Vercel KV or Upstash Redis and set one of these pairs:

- `KV_REST_API_URL` + `KV_REST_API_TOKEN`
- `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`

The relay also supports Vercel Blob with `BLOB_READ_WRITE_TOKEN`. This is the default durable store created by:

```bash
vercel blob create-store douyin-talent-relay-queue --access private --yes --environment production --environment preview --environment development
```

Store priority is:

```text
Redis/KV -> Vercel Blob -> memory
```

Without Redis/KV/Blob, the relay falls back to in-memory storage. That is only for smoke tests and is not durable.

## DingTalk HTTP body

```json
{
  "relay_token": "<RELAY_TOKEN>",
  "task_id": "{{任务编号}}",
  "wait_ready": 60,
  "reserve_quota": 0,
  "smoke": false
}
```

Headers:

```text
Content-Type: application/json
Authorization: Bearer <RELAY_TOKEN>
```

If the DingTalk HTTP component cannot pass `Authorization`, put `relay_token`
in the JSON body as shown above. The relay removes `relay_token` before storing
the job payload.

## Local worker

Run on the computer that has Chrome logged in to Douyin Life:

```bash
export DOUYIN_RELAY_URL="https://<your-vercel-domain>"
export DOUYIN_RELAY_WORKER_TOKEN="<WORKER_TOKEN>"
python3 scripts/vercel_relay_worker.py --once
```

Use `--once` for tests. Remove `--once` for continuous polling.

On macOS, the worker automatically reads the system HTTPS proxy from `scutil --proxy`.
If needed, override it manually:

```bash
python3 scripts/vercel_relay_worker.py --proxy http://127.0.0.1:7890
```
