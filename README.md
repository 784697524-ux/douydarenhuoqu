# 抖音来客达人广场获取联系方式

这个仓库封装了一个可复用的 Codex Skill/本地脚本，用于按配置表自动筛选抖音来客达人广场，获取达人基础信息和微信联系方式，并回写到钉钉 AI 表或飞书多维表。

核心目标：

- 用表格配置任务，不手工重复筛选。
- 获取达人基础数据、微信号、虚拟手机号。
- 已有联系方式自动跳过，不重复消耗每日联系方式查看额度。
- 每次运行写入结果表、达人主档、联系方式日志、每日额度审计、任务游标。

## 目录

```text
.
├── SKILL.md
├── README.md
├── agents/openai.yaml
├── references/config.example.json
├── references/schema.md
├── scripts/
│   ├── douyin-talent-contact
│   ├── douyin_browser_runner_selenium.py
│   ├── feishu_notable_adapter.py
│   ├── init_tables.py
│   ├── install_local.py
│   ├── launch_debug_chrome.py
│   ├── run_talent_task.py
│   ├── runtime_config.py
│   ├── schema_spec.py
│   └── sync_talent.py
└── tests/test_skill_package.py
```

## 前置条件

1. 本机已安装 Python 3。
2. 已登录抖音来客账号，并且该账号有达人广场权限。
3. 如果使用钉钉 AI 表：本机已有可用的 `dingtalk_tool.py`。
4. 如果使用飞书多维表：本机已有可用的 `lark-cli`，并完成登录授权。
5. Chrome 需要以 CDP 调试模式运行，默认地址是 `http://127.0.0.1:9222`。

## 安装本地命令

在仓库目录执行：

```bash
python3 scripts/install_local.py
```

安装后默认命令是：

```bash
douyin-talent-contact <任务ID>
```

如果 `~/.local/bin` 不在 PATH 中，先执行：

```bash
export PATH="$HOME/.local/bin:$PATH"
```

## 创建或修复表结构

### 钉钉 AI 表

```bash
python3 scripts/init_tables.py \
  --backend dingtalk \
  --base-id <DINGTALK_BASE_ID> \
  --write-config
```

### 飞书多维表

```bash
python3 scripts/init_tables.py \
  --backend feishu \
  --base-token <FEISHU_BASE_TOKEN> \
  --write-config
```

执行后会生成本地配置文件：

```text
~/.douyin-life-talent-contact/config.json
```

所有个人信息、表 ID、企业账号信息都应该只写在这个本地配置文件里，不要提交到仓库。

## 配置文件

可以参考：

```text
references/config.example.json
```

钉钉最小配置示例：

```json
{
  "backend": "dingtalk",
  "chrome_cdp_url": "http://127.0.0.1:9222",
  "douyin_url": "https://life.douyin.com/p/liteapp/alliance_merchant/merchant/talent/square?enter_from=pc_menu_daren_square",
  "quota": {
    "daily_quota": 30,
    "reserve_quota": 0,
    "max_contact_views": 1
  },
  "account": "auto",
  "dingtalk": {
    "helper": "~/.codex/skills/dingtalk-knowledge-manager/scripts/dingtalk_tool.py",
    "base_id": "<DINGTALK_BASE_ID>",
    "config_sheet": "<CONFIG_SHEET_ID>",
    "result_sheet": "<RESULT_SHEET_ID>",
    "master_sheet": "<MASTER_SHEET_ID>",
    "contact_log_sheet": "<CONTACT_LOG_SHEET_ID>",
    "quota_sheet": "<QUOTA_SHEET_ID>",
    "cursor_sheet": "<CURSOR_SHEET_ID>"
  }
}
```

## 启动 Chrome

```bash
python3 scripts/launch_debug_chrome.py
```

第一次启动后，在这个 Chrome 窗口里登录抖音来客。

如需绑定具体商家账号，可以在配置里的 `douyin_url` 里填入对应账号打开后的达人广场 URL。不要把带真实 `groupid` 的 URL 提交到仓库。

## 配置任务

在 `配置表` 中新增或启用一行：

| 字段 | 示例 | 说明 |
| --- | --- | --- |
| 启用 | 是 | 只有启用为“是”的任务会执行 |
| 任务ID 或 任务编号 | 001 | 命令行传入的任务编号 |
| 常驻城市 | 杭州 | 达人广场城市筛选 |
| 优势品类 | 美食 | 达人广场品类筛选 |
| 视频带货力 | Lv3, Lv4, Lv5 | 支持多选 |
| 有微信/电话 | 有 | 优先筛有联系方式达人 |
| 达人类型 | 全部达人 | 可按页面能力填写 |
| 查询次数 | 1 | 本任务最多打开多少次联系方式弹窗 |
| 每页数量 | 10 | 记录用途，页面默认每页 10 条 |

## 运行前检查

```bash
douyin-talent-contact doctor --wait-ready 60
```

返回中应看到：

```json
{
  "ok": true,
  "talent_square_ready": true,
  "next_action": "run_task"
}
```

## 安全试跑

安全试跑不会点击“查看联系方式”，不会写表，不消耗额度：

```bash
douyin-talent-contact 001 --smoke --wait-ready 60
```

## 正式执行

```bash
douyin-talent-contact 001 --wait-ready 60
```

成功后会输出类似：

```json
{
  "ok": true,
  "task_id": "001",
  "opened_contacts": 1,
  "commit": {
    "add_count": 1,
    "planned_contact_view_consumption": 1
  }
}
```

## 钉钉按钮触发（Vercel HTTPS 中转）

仓库内置了一个 Vercel Relay：

```text
vercel-relay/
```

它只负责提供公网 HTTPS 入口和任务队列，不在云端登录抖音，也不保存 Chrome Cookie。真正执行达人广场筛选和联系方式查看的仍然是本机 worker。

部署到 Vercel 后，钉钉 AI 表自动化 HTTP 请求填：

```text
POST https://<你的-vercel-域名>/api/jobs
Authorization: Bearer <RELAY_TOKEN>
Content-Type: application/json
```

Body：

```json
{
  "task_id": "{{任务编号}}",
  "wait_ready": 60,
  "reserve_quota": 0,
  "smoke": false
}
```

本机启动 worker：

```bash
export DOUYIN_RELAY_URL="https://<你的-vercel-域名>"
export DOUYIN_RELAY_WORKER_TOKEN="<WORKER_TOKEN>"
python3 scripts/vercel_relay_worker.py
```

长期使用需要持久队列。当前 Relay 支持的优先级是：

```text
Redis/KV -> Vercel Blob -> memory
```

默认推荐用 Vercel Blob：

```bash
cd vercel-relay
vercel blob create-store douyin-talent-relay-queue --access private --yes --environment production --environment preview --environment development
```

如果没有 Redis/KV/Blob，Relay 会退回内存队列，只适合烟测，不适合长期使用。

## 去重和额度规则

脚本会先执行 `prepare`，读取：

- `结果表`
- `达人主档表`
- `联系方式查看日志`
- `每日30次额度审计`

去重顺序：

1. `达人UID`
2. `抖音号`
3. `达人昵称 + 城市 + 品类`

如果达人已经有微信号：

- 不会再次点击“查看联系方式”。
- 不会再次消耗每日 30 次额度。
- 如果主档或日志中有缓存联系方式，但结果表还没有，可复用缓存写入结果表，`是否消耗额度=否`。

如果是新达人且没有缓存联系方式：

- 只有在未超过 `查询次数` 和每日额度时才会打开联系方式弹窗。
- 成功查看后写入结果表、主档表、日志表和额度审计表。

## 常见问题

### 命令找不到任务

报错类似：

```text
No active config row found where 启用=是 and 任务ID/任务编号=001
```

检查配置表：

- `启用` 是否为 `是`
- `任务ID` 或 `任务编号` 是否和命令一致

### 页面停在达人广场但命令不继续

先运行：

```bash
douyin-talent-contact doctor --wait-ready 60
```

如果 `talent_square_ready=false`，通常是 Chrome 没有登录、账号不对、页面加载失败，或 CDP Chrome 不是当前登录账号。

### 钉钉接口偶发超时

脚本已经对 `HTTP 5xx/429/socket.timeout/timed out` 做了最多 3 次重试。持续失败时，通常是网络或钉钉接口临时异常。

### 不想消耗额度

使用：

```bash
douyin-talent-contact 001 --smoke
```

或在配置表把 `查询次数` 设为 `0` 或空值，并用 `--max-contact-views 0`。

## 本仓库不应包含的敏感信息

不要提交：

- 真实 `base_id` / `sheet_id` / `base_token` / `table_id`
- 真实商家账号名称
- 带真实 `groupid` 的抖音来客 URL
- token、cookie、手机号、微信号明细

这些信息只放在本地：

```text
~/.douyin-life-talent-contact/config.json
```
