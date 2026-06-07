# Vercel HTTPS Relay for Douyin Talent Tasks

This relay gives DingTalk AI Table automation a stable HTTPS endpoint while keeping Douyin Chrome execution on the user's local machine.

## Endpoints

- `POST /api/jobs`: DingTalk button enqueues a task.
- `GET /api/next`: local worker pulls one queued task.
- `POST /api/complete`: local worker reports execution result.
- `GET /api/jobs?id=<job_id>`: query job status.

## Required Vercel environment variables

- `RELAY_TOKEN`: token used by DingTalk HTTP request.
- `WORKER_TOKEN`: token used by the local worker.

For long-term durable queue storage, connect Vercel KV or Upstash Redis and set one of these pairs:

- `KV_REST_API_URL` + `KV_REST_API_TOKEN`
- `UPSTASH_REDIS_REST_URL` + `UPSTASH_REDIS_REST_TOKEN`

Without Redis/KV, the relay falls back to in-memory storage. That is only for smoke tests and is not durable.

## DingTalk HTTP body

```json
{
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

## Local worker

Run on the computer that has Chrome logged in to Douyin Life:

```bash
export DOUYIN_RELAY_URL="https://<your-vercel-domain>"
export DOUYIN_RELAY_WORKER_TOKEN="<WORKER_TOKEN>"
python3 scripts/vercel_relay_worker.py --once
```

Use `--once` for tests. Remove `--once` for continuous polling.
