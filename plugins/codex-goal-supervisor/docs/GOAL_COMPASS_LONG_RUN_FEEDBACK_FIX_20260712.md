# Goal Compass 长跑反馈逐项修复说明

日期：2026-07-12

本轮逐行核对了三份来自 Windows 与 macOS、持续数小时到十余小时运行后的反馈：

1. `2026-07-11-codex-goal-supervisor-usage-feedback-v1.md`
2. `CODEX_GOAL_SUPERVISOR_PLUGIN_FEEDBACK_20260711.md`
3. `codex goal 插件问题反馈2.rtf`

反馈对应的运行版本主要是 `0.1.0+codex.20260710185001` 和
`0.1.0+codex.20260711135233`。本轮没有假定旧问题仍然存在，而是逐项与当前
源码、现有回归和真实命令行为对照。下面只记录确认仍存在或需要进一步收紧的
问题，以及本轮实际落地的改动。

## 1. 终态 ticket 污染后续请求

### 原因

`current_ticket.json` 在 `PASS`、`FAIL`、`DRIFT` 后仍保存完整终态 ticket。
`request`、`status` 和部分 Janitor 上下文会继续读取它，导致新请求继承旧票的
provider、domain、task_goal、acceptance 或 must_not_do。

### 改动

- `active_ticket()` 只返回 `ACTIVE` ticket。
- `request`、MDCP request signal、status 和 Janitor 当前票上下文不再使用终态票。
- `close`/`abort` 后将完整票移动到 `tickets/done` 或 `tickets/failed`。
- `current_ticket.json` 只留下小型 `NONE` 哨兵。
- 新增 `last_ticket.json`，只保存终态摘要和归档路径。
- 归档成功后删除原 pending 文件。

### 结果

终态票不再拥有后续请求的解释权。没有 ACTIVE ticket 时，符合 North Star 的
编辑请求会得到 `PROPOSE_NEW_TICKET`，不会被旧 ticket 偷换成旧任务。

## 2. ticket 历史可覆盖、同 ID 可复用

### 原因

旧 `move_finished()` 直接写目标路径；相同 ticket id 的重试可能覆盖历史。
pending、current、done、failed 之间也没有完整冲突检查。

### 改动

- 终态归档使用 exclusive create，已有文件时拒绝覆盖。
- `start` 同时检查 ACTIVE、pending、done、failed 中的 ID 冲突。
- 重试必须使用新 ID，并通过 `retry_of`/`supersedes` 表达关系。
- 终态迁移清理 pending 源文件和外置 baseline。

### 结果

历史票变为不可覆盖事实记录；恢复或重试不会悄悄改写过去。

## 3. Hook 未连接却显示 `tool_calls=0`

### 原因

旧逻辑只在 PostToolUse 中简单 `+1`，没有心跳、事件 ID、分类或连接状态。
Hook 未被信任、未触发、重复触发时，用户看到的都是同一个 `0`。

### 改动

- 新增 `.agent/runtime/hook_state.json`。
- 记录 Pre/Post 心跳、run_id、最近事件 ID和最后心跳时间。
- PostToolUse 按事件 ID 去重。
- 工具调用分类为 `read`、`write`、`validation`、`agent`、`external`、`failed`。
- 新增 `doctor`：返回 `CONNECTED_VERIFIED`、`ADVISORY_UNVERIFIED`、
  `DISCONNECTED` 或 `NO_ACTIVE_TICKET`。
- 未收到真实 PostToolUse 时，status 的 `tool_calls` 为 `null`，不会再显示假 0。
- `max_tool_calls` 只在 `CONNECTED_VERIFIED` 后执行硬计量。
- Hook 连接后重复 event id 只计一次。

### 结果

现在能区分“调用数确实为 0”和“根本没有接上 Hook”。工具预算不再用不可验证
的数据假装生效。

## 4. 公司 subagent 只有计划，没有运行事实

### 原因

`mdcp.layer_2_company_subagents` 能生成角色、模型和合同，但
`runtime_execution_verified` 永远为 false，`close` 也不检查实际运行。
主线程可以只写一份公司计划便声称多部门已经工作。

### 改动

- `start` 冻结公司 roster fingerprint 和 required roles。
- 新增内部运行命令 `company-record` 与 `company-status`。
- 每个必需角色记录 `STARTED`、`COMPLETED` 或 `FAILED`。
- `COMPLETED` 必须绑定 summary、result hash 或真实 result path 内容哈希。
- 失败尝试永久保留；允许新 agent 使用 fallback model 重试。
- role contract 新增 `fallback_models`、`fork_context=false`、完成后释放要求。
- QA 存在时在 dispatch 中保留 QA capacity。
- Hook 在必需部门尚未开始前拒绝产品写入。
- `close` 在必需部门没有完成回执时返回 `NEEDS_COMPANY_RESULTS`，ticket 保持
  ACTIVE，不运行假闭环。
- MDCP Layer 3 新增 `company_runtime_complete`。

### 结果

“生成了公司计划”和“公司真的运行并交付”变成两个不同状态。失败重试不会被
覆盖，模型 fallback 也不再等于悄悄取消该部门。

### 能力边界

这些回执是运行轨迹，不是签名或安全证明。Goal Compass 仍然不是 HMAC、审批或
不可抵赖系统；它只阻止无任何运行记录的假闭环。

## 5. 非 Git baseline 过大且只比较 size/mtime

### 原因

旧 baseline 内嵌在 `current_ticket.json`，大仓库会把状态文件膨胀到 MB 甚至更大。
文件变化只比较 size 与 mtime，内容同尺寸、恢复时间戳时会漏检。

### 改动

- baseline 外置为 `.agent/runtime/baselines/<run_id>.json.gz`。
- current ticket 只保存 baseline 路径、SHA256 和条目数。
- 16 MB 以下文件使用完整内容 SHA256；更大文件使用首尾采样哈希。
- 终态归档不保存 baseline 内容或失效引用。
- 递归忽略任意层级 `__pycache__`、`.pytest_cache`、`.mypy_cache`、
  `.ruff_cache`。
- 精确 allowed/acceptance 位于通常忽略目录时，仍扫描该目录及意外 sibling。
- SQLite WAL/SHM、PID、socket 等作为 `volatile_runtime_changes` 单独报告，
  不算产品 diff 或 drift。

### 结果

状态文件保持小型，非 Git 仓库能检测同尺寸同 mtime 的真实内容变化，也不会被
后台数据库和缓存持续打爆。

## 6. North Star、阶段目标与 current ticket 混在一起

### 原因

旧状态只有长期 North Star 和 current ticket。阶段里程碑只能被塞入其中之一，
容易让“当前阶段”覆盖“长期目标”，或让小票承担阶段级语义。

### 改动

- 新增 `.agent/program_phase.json` 和可选 `phase-set`。
- North Star 继续保存长期方向。
- program phase 保存可变阶段 goal 与 exit criteria。
- current ticket 继续只保存当前 bounded execution。
- request provenance 同时记录 North Star hash、program phase id、ACTIVE ticket id、
  acceptance fingerprint、runtime hash 和 router version。

### 结果

三层目标来源被显式拆开，用户最新一句话不能直接覆盖任何一层。

## 7. request gate 词法误判和意图替换

### 原因

- `inspect` 的子串匹配会把 `inspection result` 错当只读审计。
- read-only/meta 请求仍可能因缺少当前 acceptance 映射被拒绝。
- `ACCEPT_SIMPLIFIED` 的 accepted intent 和 action 可能引用旧 ticket task_goal。
- drift signal 不分严重度，几乎全部进入 backlog。

### 改动

- 操作类型改用完整词边界和更明确的中文意图短语。
- 只读审计允许执行，但明确 `product_edit_allowed=false`。
- stop/pause/do-not-continue 先于 anti-goal 词法判断，避免否定句被当正向扩张。
- `ACCEPT_SIMPLIFIED.accepted_intent` 保留用户原始请求；只在明确最小权限意图
  映射时生成当前票内的最小动作。
- 没有 ACTIVE ticket 时，不再继承终态票；符合 North Star 的请求进入新票提案。
- drift 根据“整体重写”与独立动作数量区分 `REJECT`、`SPLIT`、`BACKLOG`。
- request 输出 operation class、读/规划/编辑权限和完整 provenance。

### 结果

生产“inspection”不再被误判成 meta inspection；只读检查不再要求创建产品票；
纠偏句不会被关键词反向理解；简化结果不再偷换用户对象。

## 8. Janitor 范围含糊、假 CLEAN、误删风险

### 原因

无 ACTIVE ticket 时，旧 prune 默认取当前 git diff；没有 diff 便可能给出 CLEAN，
但这既不是 current-ticket 结论，也不是 full-repo 结论。

### 改动

- `prune-check`/`prune-plan` 新增显式范围：`current-ticket` 或 `full-repo`。
- 默认仍是 current-ticket；无 ACTIVE ticket 返回 `NOT_APPLICABLE`。
- 只有显式 `--scope full-repo` 才做仓库卫生盘点。
- 输出同时标明 `ticket_noise_status` 和 `repository_hygiene_status`。
- 保留现有强证据顺序：exact acceptance、validation graph、North Star source、
  live reference、core path 优先；弱关键词不能保护 artifact。
- 否定语境过滤继续生效；“不要建设 marketplace”不等于 artifact 自己是 marketplace。
- 单一负向词只进入 `REVIEW_REQUIRED`，不会自动隔离。
- Goal Janitor 继续固定为 `MARK_ONLY`；`--delete` 仍硬拒绝，文件不移动、不删除。

### 结果

清理结论带明确范围，核心文件不会因普通领域词被误杀，RBAC/marketplace 也不能
靠写入 North Star 词汇伪装成 PROTECTED。准确率提升没有被用作自动提权理由。

## 9. 浏览器、手工 QA 与运行证据没有归档

### 原因

旧票只保存命令验收，没有统一位置记录浏览器截图核验、人工检查、QA 或运行态
证据。终态报告容易丢失“为什么认为它可用”。

### 改动

- 新增 `evidence-add` / `evidence-list`。
- 支持 browser、manual、qa、validation、artifact、runtime 类型。
- 指定 path 时自动保存 SHA256。
- 证据与 ACTIVE ticket 一起进入 immutable terminal history。

### 结果

网页、服务和手工验证可以进入同一票据证据链，不再只存在于聊天文本。

## 10. 验收只看文件存在，服务没有生命周期

### 原因

`files_exist`/`contains` 能通过语法存在性，却不能证明真实行为。需要后台服务的
测试也没有 setup、healthcheck、teardown，失败后可能留残进程或状态。

### 改动

- `ready` 输出 `acceptance_quality`：`BEHAVIORAL`、`SYNTACTIC_ONLY` 或 `MISSING`。
- 文件/文本验收仍可用于小票，但明确警告它不能证明行为。
- 新增可选 `validation_lifecycle.setup`、`healthcheck`、`teardown` catalog ids。
- teardown 放在 `finally`，主验证失败也执行。
- validation lifecycle 加入 acceptance fingerprint，start 后不可移动。
- validation catalog 支持 `argv`，`{python}` 在拆词前作为 token 替换，避免 Windows
  Python 路径含空格时失效。

### 结果

语法验收不再被包装成行为证明；服务型测试能够可靠启动、健康检查和收尾。

## 11. Windows 验证依赖 Unix 命令

### 原因

verification 使用 `/bin/sh`、`true`、`false`；超时在 Windows 只 kill 父进程。

### 改动

- 测试 validation 统一为 `{python} -c ...`。
- Hook wrapper 测试按平台使用 `/bin/sh` 或 `cmd /d /s /c`。
- Windows timeout 使用 `taskkill /T /F` 终止进程树。
- 继续使用 UTF-8 reconfigure 和 `commandWindows`。
- installer 写 `.agent/goal_compass_install.json`，包含 plugin version、runtime SHA256、
  安装时间、迁移策略和安装摘要。

### 结果

测试和安装不再把 Unix 命令当成跨平台事实。当前 macOS 已完成全部验证；真实
Windows 主机仍需用同一 suite 做最终平台确认，本轮不把静态兼容误称为已跑过
Windows CI。

## 12. 输出与时间噪音

### 原因

check 同时输出完整 `mdcp_audit` 和重复 `mdcp`；暂停/系统错误时间可能被当作活跃
工作时间。

### 改动

- check 默认不再重复输出完整 `mdcp_audit`，只有 `--verbose` 才包含。
- status 保持低噪声摘要，并增加 hook、program phase、company runtime 当前动作。
- 活跃计量和 wall-clock 分开；单次空闲间隔有限制，不把整夜暂停都算执行预算。
- company 未完成时，PASS_READY 不再建议直接 close，而是提示完成或重试部门。

### 结果

机器状态与操作建议一致，重复 MDCP 内容减少，暂停时间不再自动把票打爆。

## 本轮没有重新引入的内容

- HMAC
- signed ledger
- board approval
- reverse signal
- role signoff
- security governor
- MCP firewall
- 自动删除

## 验证结果

```text
python3 -m unittest -q verification.tests.test_goal_compass
Ran 197 tests in 50.852s
OK

python3 -m unittest discover -s verification/tests -q
Ran 197 tests in 44.524s
OK

python3 assets/governor-harness/.agent/selftest/test_goal_compass.py
Goal Compass selftest OK
real 0.47s
```

## 仍然保留的诚实边界

1. Goal Compass 不是安全边界；Hook 未连接时由 `doctor` 明确报告，而不是假装执行。
2. 公司回执是执行轨迹，不是签名证明；它解决“完全没有运行证据”，不解决不可抵赖。
3. Janitor 的语义分类仍可能存在误差，所以保持 MARK_ONLY，不因本轮回归通过而提权。
4. 外部 scanner 仍只提供候选信号，不能触发删除。
5. Windows 兼容代码与测试已修，但本轮执行环境是 macOS，仍需 Windows 实机再跑同一套验证。

