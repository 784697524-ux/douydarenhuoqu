# Schema

The skill creates six tables with stable Chinese names:

- `配置表`: task filters and run status
- `结果表`: collected talent basics and WeChat/contact fields
- `达人主档表`: dedupe cache for known contacts
- `联系方式查看日志`: every popup view or cached reuse
- `每日30次额度审计`: daily quota snapshot per account
- `任务执行游标表`: run cursor and status history

Required config fields:

- `启用`: `是` means runnable
- `任务ID` or `任务编号`: selected by `--task-id`
- `查询次数`: maximum new contact popups in one run
- `有微信/电话`: usually `是`
- `达人类型`: `全部达人`, `短视频达人`, or `直播达人`

Dedupe key order:

1. `达人UID`
2. `抖音号`
3. hash of `达人昵称 + 达人城市 + 达人品类`

Quota logic:

- Rows in `联系方式查看日志` count as quota only when `日期` and `账号` match the run and `消耗额度=是`.
- Existing result/master/contact-log WeChat values are reused with `是否消耗额度=否`.
- `查询次数` and remaining daily quota both cap contact popup opens.

Sensitive data rule:

- Do not store real DingTalk base IDs, Feishu base tokens, Douyin group IDs, account names, or company/person names in skill files.
- Store those values only in the user-local config file.
