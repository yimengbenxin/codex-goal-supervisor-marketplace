# Goal Compass 实时反馈与复用优先机制

## 至高规则

两项能力都必须产生净收益：

- 问题反馈不能因为服务器不可用而拖住产品执行。
- 复用探测不能在每个工具调用上重复联网。
- 发现能直接复用的成熟能力时，避免重新实现带来的开发和维护成本。
- 候选只是证据，不允许仅凭关键词自动下载或执行第三方代码。

## 1. 实时问题反馈

### 自动捕获范围

- PreToolUse 边界拦截。
- `ready` 和 `start` 的合同/路径/复用门阻断。
- `check` 的 drift、预算、验证或产物阻断。
- `close` 的失败与缺失运行结果。
- AI 显式报告的 false positive、false negative、wrong status、runtime error 和 workflow friction。

### 可靠性

每条事件先原子写入：

```text
.agent/runtime/feedback-outbox/<event-id>.json
```

默认不进行网络请求。只有当前项目显式授权上传后，才以短超时 HTTP POST 到服务器；2xx 后删除 outbox 文件并写发送摘要。网络失败时：

- 产品命令继续执行；
- 事件留在 outbox；
- 进入 5 分钟失败冷却，避免每次工具调用重复等待；
- 下一次反馈或显式 `feedback --flush` 重试。

这个模式沿用了成熟遥测系统的 durable queue / retry 思路，但没有把完整 OpenTelemetry Collector 或 Sentry SDK 强行安装进每个用户项目。Goal Compass 仍保持 Python 标准库运行时。

### 隐私边界

- 企业/工作场景和无交互安装默认只保存在本地。
- 自动注册得到的设备凭证和 Hook 事件都不能单独获得上传权限。
- 上传授权按项目保存，可随时撤销；撤销不删除本地待处理事件。

上传内容仅包含：

- 哈希后的项目身份；
- 插件版本、OS、Python 主次版本；
- ticket id、命令名、错误类别、规则 id、状态与建议动作；
- 有界且脱敏的治理上下文。

不会采集：

- 用户 prompt；
- 源文件内容；
- 环境变量值；
- API Key、Token、密码或 Authorization；
- 用户主目录绝对路径。

### 服务器连接

用户无需配置服务器地址或 Token。当前项目首次明确授权上传时，插件自动调用受限设备注册协议，
领取本机独立、可撤销的凭证并保存到用户私有配置目录。没有授权时不注册、不联网。

接收器不提供网页、文件、ZIP 或 multipart 上传。只接受 Goal Supervisor 固定 JSON 事件；
不合规请求仅保留拒绝原因、体积、类型和哈希，不保存可疑正文。

用户在某个项目中明确说“上传/同步插件问题”后，AI 才为当前项目执行授权和发送；只说
“记录问题”仍然只写本地 outbox。

```bash
python3 .agent/goal_compass.py feedback-config \
  --context enterprise \
  --allow-upload --confirm-upload --flush
```

`feedback-config --deny-upload` 会立即回到 `local_outbox_only`。`--enable`
只控制本地捕获，不代表同意上传。

显式上传时，只有事件结果同时满足 `uploaded=true` 和 `queued_locally=false` 才表示服务器已接收。
`captured=true` 只表示本地 durable outbox 已记录；自动注册或网络失败时命令返回非零，事件仍留在本地等待重试。

服务器接收一个 JSON object，并返回任意 2xx。事件中的：

```json
{
  "maintainer_action": "OPEN_REPRODUCTION_AND_REPAIR_TICKET"
}
```

表示中央接收器应启动插件维护仓库里的“复现 -> 最小失败测试 -> 修复 -> 全量回归 -> 发布”流程。用户项目内的插件不会根据未经验证的远程反馈自行修改源码。

服务器公网只开放事件上传，不开放反馈下载。插件维护者在发布新版本前通过 SSH 增量拉取：

```bash
python3 scripts/fetch_feedback.py \
  --remote <ssh-host-alias> \
  --output-dir feedback-inbox
```

游标由服务器接收时间和 `event_id` 共同组成，同一秒到达的事件也不会被跳过。拉取后先聚类、
复现并加入失败测试，只有确认仍存在于当前源码的问题才进入修复。

## 2. 复用优先

### 何时运行

- 项目第一次确认 North Star 或第一次进入实现：运行一次项目级探测。
- Ticket 工作：`ready` 和 `start` 只确认项目级探测存在，五天内复用同一结果。
- 新线程、续聊、新 ticket 和不同的小动作都不会在五天内重复联网检索。
- read-only：跳过。
- 连续运行达到 5 天：下一次产品写操作前强制刷新一次。

### 检索输入

检索 query 来自：

- confirmed North Star；
- 当前阶段；
- 未完成 pending tickets；
- 当前 task goal / must_do；
- backlog 中尚未执行的具体动作；
- 项目语言/工具链标记。

默认调用 GitHub Repository Search，并为候选记录 stars、language、license、archived、pushed_at 和 latest release。缓存作用域是项目，不是 task、ticket、线程或工具调用。

### 强候选门

候选只有同时具备较强任务匹配、明确许可证、非 archived、最低成熟度和语言兼容性时，才成为 `DIRECT_REUSE_CANDIDATE`。

出现强候选后先做兼容性处置：

- `ADOPT_EXISTING`
- `EXTEND_EXISTING`
- `REJECT_WITH_EVIDENCE`

`REJECT_WITH_EVIDENCE` 只用于证明候选不适配。确认适配的工具必须采用或扩展，并同时提供项目接入计划与 validation catalog id。Goal Compass 自动把它写入 ticket 的 `must_do`、`reuse_integration`、`validation_ids` 和 `acceptance.commands_pass`；close 验证通过后才标记为 `VERIFIED`。只调研、不接入不算完成。系统不会自动 clone、安装或执行候选。

### 五天后更新检查

刷新时会比较历史候选的 latest release 和 pushed_at。发现变化后，要求记录：

- `INCORPORATE`
- `DEFER`
- `NOT_APPLICABLE`

这样既能看到旧工具的新能力，也不会因为每个 upstream commit 都自动改写当前产品范围。

## 3. 已复用的公开能力

- GitHub REST repository search/repository metadata：候选检索、许可证、语言、活跃度。
- GitHub latest release endpoint：已见候选版本刷新。
- OpenTelemetry 的 queued retry / persistent queue 原则：反馈先落盘、失败重试、监控 pending 数。

参考：

- https://docs.github.com/en/rest/search/search
- https://docs.github.com/en/rest/releases/releases
- https://opentelemetry.io/docs/collector/resiliency/

没有直接引入完整 OpenTelemetry/Sentry 依赖，因为它们会显著增加每个目标项目的安装和运行成本；当前需求只需要一类低吞吐治理事件，标准库 outbox 已覆盖必要可靠性。
