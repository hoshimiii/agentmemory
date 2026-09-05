# AgentMemory 定时记忆候选整理需求

状态：M9 本地实现与隔离安装验证完成；真实每日调度与 provider 调用未执行
适用分支：`codex/m9-scheduled-memory-candidates`
基线：P0 提交 `e81deed`

## 1. 目标

AgentMemory 增加一个默认关闭的定时 AI 整理插槽。用户选择 AI 提供方、模型和 cron 后，外部调度器可以每天调用 AgentMemory；AI 只读检查当前 Git 项目的可验证事实，输出可能值得长期保留的候选，AgentMemory 将合格内容写入当前 worktree 的本地 candidate 目录并返回审核报告。

候选不是持久记忆。只有人类随后明确执行 `review --candidate <id> --confirm`，候选才可沿既有 receipt 信任路径进入 reviewed memory。

## 2. 为什么这样实现

- AI 擅长从近期代码、测试、文档和 Git 事实中归纳候选，但不能替代人判断内容是否长期有效。
- 把 AI 进程限制为只读、再由 AgentMemory 解析和写 candidate，可避免不同工具需要无人值守写权限。
- provider、model、cron 与开关放在 worktree-local 配置中，便于不同项目和 worktree 使用不同策略，也不会把机器配置提交到 Git。
- 使用固定 adapter registry 和 argv 数组，避免任意 shell 模板带来的命令注入与不可审计行为。

## 3. 配置合同

配置路径：

```text
.continuity/local/worktrees/<worktree-id>/scheduler.json
```

字段：

```json
{
  "schema_version": 1,
  "repository_id": "<sha256>",
  "worktree_id": "<sha256>",
  "enabled": false,
  "provider": "codex",
  "model": "gpt-5.6-terra",
  "cron": "0 3 * * *",
  "timezone": "local",
  "reasoning_effort": "medium"
}
```

约束：

- `provider` 仅允许 `codex`、`claude`、`gemini`。
- `repository_id` 与 `worktree_id` 必须和读取时的当前 Git identity 完全一致；仅依赖目录隔离不构成身份校验。
- `model` 是 1 至 128 个窄字符模型名，只允许字母、数字和 `._:/@+-`，首字符必须是字母或数字。
- `cron` 是五字段数字型 POSIX 子集，支持 `*`、数字、范围、列表和步长；分钟、小时、日、月、周分别检查合法范围。
- `cron` 最长 128 字符，只允许 ASCII 空格分隔；DOW 接受 `0..7`，其中 `0/7` 的含义以及 DOM/DOW 同时受限时的触发语义由外部 scheduler 决定。
- 不支持秒字段、`@daily` 等宏、月份/星期名称、Quartz 的 `? L W #` 或 provider 原生 recurrence。
- `timezone` 是 1 至 64 个非控制字符；它随计划返回，由外部调度器解释，AgentMemory 不计算下一次运行时间。
- `reasoning_effort` 仅 Codex 使用，可选值为 `none|minimal|low|medium|high|xhigh|max|ultra`；其他 provider 必须为 `null`。
- 配置不得包含凭据、环境变量值、任意 executable、任意 argv 或 shell 字符串。

## 4. CLI 合同

```text
agentmemory --repo <repo> schedule configure --provider <codex|claude|gemini> --model <model> --cron <expr> [--timezone <label>] [--reasoning-effort <value>] [--enable]
agentmemory --repo <repo> schedule enable
agentmemory --repo <repo> schedule disable
agentmemory --repo <repo> schedule status
agentmemory --repo <repo> schedule plan
agentmemory --repo <repo> schedule run [--dry-run]
```

- `configure`、`enable`、`disable` 是显式写操作；配置写入必须加锁、原子、幂等并保持 worktree 隔离。未初始化时 `configure` 失败；每次 `configure` 未带 `--enable` 都写回 `enabled:false`，避免配置变化后静默延续旧授权。
- `status` 和 `plan` 只读；未配置时返回 `configured:false, enabled:false`。
- `plan` 返回 cron、timezone、cwd、provider、model、候选上限和结构化 argv 预览，供任意外部 schedule 适配；不创建系统任务。
- `enable` 在缺少合法配置时失败；`disable` 在缺少配置时无副作用地返回 disabled。
- `run --dry-run` 等价于安全计划检查并返回 `runnable`，不要求 enabled、不启动 AI、不写 candidate。
- `run` 仅在 `enabled:true` 时启动 provider；disabled、缺失、损坏或跨 worktree 配置必须失败关闭。

## 5. Provider adapter

### Codex

- 使用 `codex exec`、`--ephemeral`、`--sandbox read-only`、`--model`、`--output-schema` 和 `--output-last-message`。
- reasoning effort 通过单个受验证的配置覆盖参数传入。
- 不使用 `danger-full-access`、workspace-write、approval bypass 或 shell。

### Claude Code

- 使用 `claude -p`、`--no-session-persistence`、`--permission-mode plan`、`--model`、`--output-format json` 和 `--json-schema`。
- stdout 必须是 Claude JSON envelope，且只读取其中唯一的 `structured_output` 字段；无结构化结果或该字段类型错误即失败，不回退读取 `result` 或扫描其他文本。其他元数据字段不参与候选解析。
- 不使用 bypass permissions 或写模式。

### Gemini CLI

- 使用 `gemini -p`、`--approval-mode plan`、`--model` 和 `--output-format json`。
- stdout 必须是 Gemini JSON envelope，只从唯一的 `response` 字符串解析候选 JSON；存在 `error`、缺少字段或响应类型错误即失败，不扫描其他文本。
- 不使用 YOLO 或 auto-edit。

所有 adapter：

- 使用 `subprocess` argv，不通过 `shell=True`；model 只能作为已验证的独立参数，reasoning override 只能由固定键与枚举值构造。
- executable 必须由 `shutil.which()` 解析为绝对路径后调用；Windows 只查询并接受 `${provider}.exe`，拒绝 `.cmd`、`.bat`、`.ps1` 和无扩展名包装器，不回退到 shell 或 `cmd.exe`。这降低 PATH 漂移与脚本包装器解释 prompt 的风险，但不证明该可执行文件来自官方发布者。
- cwd 固定为当前仓库根。
- executable 从 PATH 解析；找不到时返回不泄露环境的失败报告。
- 因此 Windows 上未提供原生 `.exe` 的 Claude 或 Gemini 会被视为不可用；这是 fail-closed 行为。
- stdout、stderr 和 Codex final-output 使用临时文件与运行期大小监测；设置有限超时和输出字节上限。超时、非零退出、非法 UTF-8、超限或非法 JSON 都不得写 candidate，临时文件必须在 `finally` 清理。
- read-only/plan 是被选 provider CLI 提供的安全边界，不是 AgentMemory 提供的 OS/内核沙箱；provider 仍可能读取其自身配置或进行模型 API 通信。

## 6. AI 输入与输出

AI 输入只允许说明其读取当前仓库中的 Git、代码、测试、规范和 `CONTEXT.md`。明确禁止读取 transcript、`PLUGIN_DATA`、平台记忆、凭据、用户主目录和其他项目；禁止运行网络查询和修改文件。

输出合同：

```json
{
  "summary": "本轮判断",
  "proposals": [
    {
      "kind": "decision",
      "summary": "候选摘要",
      "semantic_role": "fact",
      "content_json": "{\"decision\":\"...\",\"evidence\":\"...\"}",
      "paths": ["relative/path"],
      "experience_json": "null"
    }
  ]
}
```

- 最多 5 条 proposal；数组可为空。
- kind 复用既有 `decision|incident|constraint|strategy|warning`。
- 为兼容 Codex Structured Outputs，provider wire proposal 只使用严格对象字段 `kind`、`summary`、`semantic_role`、`content_json`、`paths`、`experience_json`；所有对象均设置 `additionalProperties:false`，不使用 `allOf`、`if`、`then` 或 `else`，也不含未约束的 object 值。
- `content_json` 是有上限的 JSON 编码字符串，运行时必须严格解析为 object。`experience_json` 也是有上限的 JSON 编码字符串；Strategy/Warning 必须解析为完整 v2 `experience` object，其他 kind 必须解析为 `null`。
- 解码后恢复既有内部 proposal 的 `content` 与 `experience`；继续通过既有 JSON shape、路径、大小、secret scan 和 schema 校验。
- 模型不得提供 review 状态、receipt、project record、可信度分数、命令权限或持久记忆 ID。

## 7. 写入与幂等

- provider 完整输出通过批次外层解析后才开始 candidate 写入。
- provider 启动前记录 repository/worktree/branch/head，返回后再次比对；若运行期间 checkout 变化，整批零写入失败。
- 每条 proposal 的 candidate ID 由 repository ID、worktree ID、当前 branch、当前 HEAD 和规范化 proposal 的 SHA-256 派生；同一 checkout 的同一 proposal 重试幂等，避免同一 HEAD 的分支切换冲突。
- 定时生成的 candidate 固定记录 `provenance.source: scheduled-ai`，手工 CLI candidate 继续记录 `cli`；provider 输出不能选择或覆盖来源。
- 同一批次的重复规范化 proposal 只处理一次，其余报告为 `duplicate`。
- 外层 batch envelope 非法时整轮失败；单条 proposal（包括 JSON 编码字段无法解析或配对错误）验证失败时记录为 rejected，不转换为更宽松类型；其他独立合法 proposal 可继续写入。
- executable、进程、I/O、锁、磁盘或身份变化属于 operational failure，立即停止；只有单条 schema、secret、path 校验失败允许继续下一条。
- 写入位置仍是 `.continuity/local/worktrees/<worktree-id>/candidates/`。
- 不创建 review receipt，不写 `.continuity/shared/records/`、`.continuity/shared/experiences/` 或 `CONTINUITY.md`。

## 8. 人工审核报告

成功或部分成功的稳定报告至少包括：

- provider、model、cron 与运行状态；
- AI 摘要；
- 每条 candidate 的 id、kind、summary、created/idempotent 状态；
- rejected 数量和不泄密的原因类别；
- `requires_human_review:true`；
- 明确说明没有 review 或 promotion。

报告通过 stdout 返回给外部调度器。M9 不另建报告数据库或 Markdown 日志。

## 9. 安全与授权边界

- 开关默认关闭。启用只授权定时创建 local candidate，不授权 review、promotion、删除、提交、推送、部署或其他外部写入。
- AI 的自述不是证据。候选中的 evidence 仍是待人工核对的不可信内容。
- 任何记忆都低于系统/开发者指令、用户当前请求和当前仓库证据。
- 配置、provider 输出和报告执行 secret scan；错误输出不得回显模型原始敏感文本、绝对用户路径或凭据。
- live provider 调用可能联网、计费并受各工具认证状态影响；单元/E2E 验收使用 mock，不进行真实付费调用。

## 10. 多层级 Checklist

### L0：合同

- [x] 候选整理、人工审核、持久记忆三层边界唯一且无隐式晋升。
- [x] provider、model、cron、timezone、开关和输出合同均有上限与失败模式。
- [x] scheduler 安装、live provider、合并、发布均保持独立授权。

### L1：配置与 cron

- [x] 未配置/disabled 状态安全可读，run 失败关闭。
- [x] 三种 provider 配置合法，provider-specific 字段不串用。
- [x] cron 的通配、数字、范围、列表、步长及所有边界通过。
- [x] 秒字段、宏、名称、越界、零步长、控制字符和超长值被拒绝。
- [x] config 原子、幂等、worktree 隔离，路径/symlink/reparse/special file 防护不退化。

### L2：Adapter

- [x] 三个 adapter 都生成 argv 数组并使用 read-only/plan 权限。
- [x] model 只作为单个参数，不发生 shell 拼接。
- [x] Codex schema/output 临时文件安全清理；Claude/Gemini 结构解析严格。
- [x] executable 缺失、超时、非零退出、非法 UTF-8、超限与坏 JSON 不写 candidate。

### L3：候选与报告

- [x] 0 至 5 条 proposal 可处理，超过 5 条整批拒绝。
- [x] 相同 HEAD+proposal 重试幂等；不同内容不会静默覆盖。
- [x] Strategy/Warning 继续通过 v2 规则，普通 kind 不能夹带 experience。
- [x] secret、非法路径、超限和 malformed proposal 只产生不泄密 rejection。
- [x] 运行前后 shared records、shared experiences、receipts、`CONTINUITY.md` 与 Git tracked state不变。
- [x] 报告明确列出 created/idempotent/rejected 与 `requires_human_review:true`。

### L4：兼容与最终验收

- [x] 既有 108 项基线测试保持通过。
- [x] Hook、SessionStart、PreCompact、OpenViking 和 experience match 输出不变。
- [x] README、SECURITY、PRIVACY、Skill 与实际边界一致。
- [x] 两个 Python 入口、compile、Python 3.9 AST、JSON、Skill、Plugin、diff 检查通过。
- [x] fresh Terra xhigh 独立审查无未解决 P0/P1 finding。

## 11. 后续数据提取与效用验证需求（M10，未实现）

M9 只负责生成待审核 candidate，不声称记忆已经改善任务结果。后续可观测性必须沿同一条关联链记录：

```text
经历事件 → 候选提取/写入 → 持久化 → 检索候选 → 筛选排序 → 注入上下文 → 影响决策 → 任务结果
```

### 11.1 独立开关与存储边界

- 增加独立于 `scheduler.enabled` 的 `observability.enabled`，默认关闭；开启候选整理不等于授权记录 trace。
- trace 只写当前 worktree 的 ignored 本地目录，建议路径为 `.continuity/local/worktrees/<worktree-id>/observability/events.jsonl`，不得写 shared memory、Git tracked 文件或跨项目数据库。
- 每条事件都带 `event_id`、`correlation_id`、事件类型、时间、`repository_id`、`worktree_id`、branch、HEAD，以及存在时的 candidate/record/memory ID；这些字段用于串联各阶段，不作为可信度证明。
- 默认不保存原始对话、完整 prompt、provider stdout/stderr、隐藏推理、凭据或环境变量值。查询和上下文只记录不可逆摘要或经 secret scan 的有界摘录；模型、provider 和配置仅记录非敏感标识或配置摘要。
- trace 必须可导出、可删除、可轮转；初始实现采用一个简单上限（例如 30 天或 10 MiB，先到者生效），超过上限前完成原子轮转，不另建数据库或遥测服务。

### 11.2 最小事件合同

| 事件 | 必须记录 | 不得推断 |
| --- | --- | --- |
| `write_attempt` / `write_result` | 触发方式、写入原因、候选类型、校验/去重结果、目标作用域 | AI 自述的成功率或重要性 |
| `retrieval` | 触发点、查询摘要、搜索作用域、候选 ID、rank、score、过滤原因、延迟 | 未实际返回的候选内容 |
| `injection` | 注入的 ID、顺序、UTF-8 字节数、预算、裁剪/冲突原因 | 仅因召回而声称模型已使用 |
| `outcome` | 可观察的任务结果、人工纠正、重试、轮数、工具调用和成本摘要 | 隐藏思维链、未经验证的因果归因 |

`used_by_agent`、`affected_decision` 与 `task_success` 必须是可空字段：仅接受显式工具事件、可核验结果、人工标注或受控实验标注；不得根据模型措辞自动判定为真。

### 11.3 检索与注入验收

- 检索 trace 必须明确记录 `project_id/repository_id`、`worktree_id`、session/task 的本地不透明 ID、记忆版本和生命周期状态，证明作用域过滤发生在排序与注入之前。
- 对 stale、deprecated、superseded、冲突和跨项目候选记录稳定的过滤原因；这类内容默认不得进入自动注入。
- 注入预算按已激活关系数量和实际条目大小动态增长，但必须有硬上限、逐项成本与最终裁剪记录；不得固定假定 6 KiB，也不得无限扩张上下文。
- 只有 `injection` 事件能够证明检索结果确实进入模型可见上下文；retrieval hit 不能替代注入证据。

### 11.4 日报与人工升格

- 每日任务从 trace 和本轮 candidate 报告生成一份人可审核的摘要：新增/幂等/拒绝候选、主要写入原因、检索/注入异常、stale 或冲突提示、数据链缺口和待确认的升格项。
- 日报只能建议“保留、修改、拒绝或标记过期”，不能执行 review、promotion、删除、同步或修改评测规则。
- 生成候选的 Agent 不得修改实验集、评分逻辑、晋升阈值或自己的 trace；自报告指标不能作为晋升证据。

### 11.5 最小反事实实验

使用同一批连续任务对比 `No Memory`、`System Memory`、`Oracle Memory` 和 `Distractor/Wrong Memory`；固定模型、参数、初始上下文、工具环境和重复次数。首轮采用约 30 个任务并每组重复 3 次：10 个早期信息依赖、5 个用户偏好、5 个项目状态更新、5 个新旧冲突、5 个高相似跨项目隔离任务。

验收分三层：

- 写入质量：覆盖率、错误率、重复率、冲突率、跨项目污染率和过期比例。
- 检索质量：Recall@K、Precision@K、MRR/nDCG、注入成功率、延迟和 Token 成本。
- 任务效用：任务成功率、用户纠正、错误重试、完成轮数、时间/Token/工具成本和负迁移率。

主判据是 `Success_system_memory - Success_no_memory`，召回率提高不能单独证明记忆有用。净效用可按任务设定权重计算：`ΔTaskSuccess - TokenCost - Latency - MemoryErrors - Interference`。

### 11.6 日常运行判定

只有同时满足以下条件，单次日常运行才可报告为正常：外部 scheduler 确实触发；provider 退出码为 0；输出严格解析；候选被创建、幂等识别或有界拒绝；shared memory 与 Git tracked 状态未变化；日报产生；本轮可观察阶段都有相同 `correlation_id` 或明确的缺口原因。

M9 当前没有 trace 写入、检索/注入关联、日报持久化或反事实评测，因此只能离线证明“候选整理管线和人工审核边界按合同工作”，不能证明“每日任务已实际触发”或“记忆改善了最终任务”。
