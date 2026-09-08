---
name: douyin-life-talent-contact
description: Use when a local operator needs to initialize DingTalk AI Table schemas, run Douyin Life/抖音来客达人广场 filters in Chrome, avoid duplicate contact lookups, and write influencer basics plus WeChat contact information back to configured tables.
---

# 抖音来客达人广场获取联系方式

Use this skill for tasks like: "按配置表执行达人广场任务", "创建达人联系方式回填 AI 表", "运行任务 001 并避免重复查看联系方式".

## Workflow

1. Install the public DingTalk CLI and log in once:

```bash
npm install -g dingtalk-workspace-cli
dws auth login
```

2. First run auto-provisions everything. Either run a task directly:

```bash
python3 scripts/run_talent_task.py --task-id 001 --wait-ready 60
```

…which creates the Base「达人广场筛选与联系回填配置」and all six tables on first use, or provision explicitly:

```bash
python3 scripts/init_tables.py --create-base --write-config
# 或在已有 Base 内补齐六张表：
python3 scripts/init_tables.py --base-id <DINGTALK_BASE_ID> --write-config
```

3. Fill one enabled config row in `配置表`:

- `启用`: `是`
- `任务ID` or `任务编号`: e.g. `001`
- filter fields: `常驻城市`, `优势品类`, `视频带货力`, `有微信/电话`, `达人类型`
- `查询次数`: max contact popups for this task

4. Start or connect Chrome CDP:

```bash
python3 scripts/launch_debug_chrome.py
```

Log in to Douyin Life in that Chrome window once.

5. Smoke test without viewing contacts or writing tables:

```bash
scripts/douyin-talent-contact 001 --smoke --wait-ready 60
```

6. Run the real task:

```bash
scripts/douyin-talent-contact 001 --wait-ready 60
```

Install the short command locally if desired:

```bash
python3 scripts/install_local.py
douyin-talent-contact 001 --wait-ready 60
```

## Guardrails

- Never open `查看联系方式` before `prepare` returns `skip_keys`, cached contacts, and available quota.
- Dedupe order is `达人UID`, then `抖音号`, then `达人昵称 + 城市 + 品类`.
- Reuse cached WeChat from `达人主档表` or `联系方式查看日志`; cached reuse does not consume daily quota.
- Keep first runs small: use `--smoke` or set `查询次数=1` before a large run.
- Do not hardcode user table IDs, account names, `groupid`, or company links in this skill. Put user-specific values in `~/.douyin-life-talent-contact/config.json` only.

## Scripts

- `scripts/init_tables.py`: creates or repairs the 6-table schema and writes local config; supports creating a brand-new Base first.
- `scripts/run_talent_task.py`: config-driven runner: auto-provisions tables, applies browser filtering, looks up contacts, writes results/cursor/status back.
- `scripts/douyin_browser_runner_selenium.py`: Selenium/CDP browser collector used by the current runner; it handles Chrome 148+ CDP behavior and waits for filtered rows before writing.
- `scripts/sync_talent.py`: table prepare/commit/verify logic (dedupe, quota, record mapping).
- `scripts/dws_client.py`: the only module that talks to the `dws` CLI; converts fieldId-keyed cells to Chinese field names.
- `scripts/launch_debug_chrome.py`: starts a dedicated Chrome profile on CDP port `9222`.

## References

- Read `references/schema.md` before changing field names.
- Use `references/config.example.json` when creating a user-specific config manually.
