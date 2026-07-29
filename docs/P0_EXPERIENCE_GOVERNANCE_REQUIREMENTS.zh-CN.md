# AgentMemory P0 经验治理需求

状态：已完成实现与验收
适用分支：`codex/m8-p0-experience-governance`
基线：AgentMemory 0.1.1，提交 `06ddbcc`

## 1. 目标

P0 在现有可信连续性系统旁增加一个私有、项目隔离、证据驱动的经验层，使 SuperRouter 能在收到明确任务信号后获得紧凑的处理策略与失败警告。

P0 必须回答四个问题：

1. 什么经验可以保存：`strategy` 与 `warning`。
2. 什么经验可以生效：只有当前项目中经过显式复核、具有本地 receipt、仍为有效生命周期且匹配当前任务的经验。
3. 为什么相信它：只能依赖当前仓库身份、内容完整性、显式复核和可核验的执行元数据，不能依赖 Agent 自报分数。
4. 给模型多少上下文：根据实际激活的策略—警告关系动态增长，但保持确定性、完整记录和硬安全上限。

P0 不替换现有 checkpoint、项目事实、OpenViking 或 SuperRouter：

- checkpoint 回答“当前工作进行到哪里”；
- v1 项目记录回答“哪些决策、事件和约束已确认”；
- OpenViking 回答“项目文档中可能有哪些相关资料”；
- P0 经验回答“遇到这类任务时，经过复核的处理方法和失败警告是什么”；
- SuperRouter 仍负责需求、架构、路由、执行和最终验收。

## 2. 为什么实现

### 2.1 Strategy

当前 `decision`、`incident`、`constraint` 能保存事实，但不能严格表达可匹配、可执行、可验证的处理策略。`strategy` 将可复用经验压缩为一个短控制对象，避免把完整 SOP 或历史记录全部塞入上下文。

### 2.2 Warning

失败经验必须与成功策略分开。`warning` 只描述已知失败条件、禁止行为或回退要求，避免不断扩充 Strategy 并稀释其控制信号。

### 2.3 生命周期与谱系

不可变记录目前只有 candidate 与 active 两种状态，不能说明某条经验已经被替代或废弃。P0 通过新记录引用旧记录来推导 `superseded` 和 `deprecated`，不修改已复核记录及其 receipt。

### 2.4 适用性

项目级经验不代表任何任务都适用。P0 要求每条经验声明至少一个任务类型、问题信号或错误模式，并在读取时使用明确输入做精确匹配。

### 2.5 验证证据

P0 保存命令、退出码、执行时间、Git head 和可选结果摘要哈希。它们是完整性保护的审计元数据，不是自动晋升依据，也不证明命令覆盖了真实目标。

### 2.6 动态上下文

固定 6 KiB 适合无任务信号的 SessionStart 恢复，但不适合显式任务匹配。P0 根据被激活的 Strategy—Warning 关系数量增加预算，使相关警告能随策略进入上下文，同时避免无界增长。

## 3. 非目标

P0 不实现：

- Capsule 固化、EvolutionEvent、成功率学习、离线 replay、shadow routing；
- 自动信号提取、会话全文或 reasoning trace 读取；
- 自动执行验证命令、自动复核、自动晋升、自动变异；
- EvoMap Hub、GDI、积分、公共资产导入或跨项目经验迁移；
- daemon、MCP、App、UI、云同步或新 Hook 事件；
- OpenViking 写入，或把 OpenViking 命中作为复核证据；
- 修改现有 SessionStart 行为或 6000 字节恢复胶囊；
- 安装、推送、合并、发版或部署。

## 4. 核心边界

1. v1 记录与 `schemas/record-v1.schema.json` 保持兼容；不得迁移或重写已有文件。
2. P0 使用独立 `schema_version: 2` 经验记录和独立 tracked sidecar 目录。
3. candidate、显式 `review --confirm`、精确 Git 身份、本地 receipt、内容哈希、secret scan、原子写和 fail-closed 加载仍是唯一信任路径。
4. 经验始终是低优先级、不可信建议，不能覆盖系统、开发者、用户指令或当前仓库证据。
5. 匹配是显式、只读、确定性的；不得读取 transcript、`PLUGIN_DATA`、Hook 任务文本或 OpenViking。
6. 生命周期和关系 ID 只用于筛选与组织；任何引用都不能绕过独立记录的校验、receipt、项目身份和适用性。
7. 生成经验的 Agent 不能通过分数、成功率或自选测试获得自动晋升。

## 5. 存储布局

```text
.continuity/
├── manifest.json                         # 保持 v1 内容不变
├── CONTINUITY.md                         # 保持 v1 派生视图，不渲染经验
├── shared/
│   ├── records/                          # 现有 v1 项目记录
│   └── experiences/                      # 新增、tracked、v2 已复核经验
└── local/
    └── worktrees/<worktree-id>/
        ├── candidates/                   # v1/v2 本地候选，按 schema 分派读取
        └── receipts/                     # v1/v2 通用 id + content_hash receipt
```

不修改 `MANIFEST_TEMPLATE`。旧版本会忽略 `shared/experiences/`，因此代码回退后 v1 resume 仍可工作。P0 数据不自动删除。

## 6. v2 经验数据合同

### 6.1 公共外形

```json
{
  "schema_version": 2,
  "id": "cand-storage-receipt-repair",
  "record_type": "candidate",
  "kind": "strategy",
  "status": "candidate",
  "semantic_role": "inference",
  "summary": "重新验证 receipt 后再恢复项目经验。",
  "scope": "local",
  "applies_to": {
    "repository_id": "<64 lowercase hex>",
    "worktree_id": "<64 lowercase hex>",
    "branch": "main",
    "head": "<40 lowercase hex>",
    "paths": ["agentmemory/storage.py"]
  },
  "provenance": {
    "source": "cli",
    "evidence_refs": [],
    "source_record_id": "cand-storage-receipt-repair"
  },
  "content": {
    "body": "确认 record id 与 content hash 均匹配；缺失时跳过，冲突时失败关闭。"
  },
  "experience": {
    "applicability": {
      "task_types": ["bugfix"],
      "signals": ["memory.receipt"],
      "error_patterns": ["receipt-mismatch"]
    },
    "evidence": {
      "checks": [
        {
          "command": "py -3 -m unittest discover -s tests -p test_memory_review.py -v",
          "exit_code": 0,
          "observed_at": "2026-07-29T12:00:00Z",
          "git_head": "<40 lowercase hex>",
          "result_digest": null
        }
      ]
    },
    "lineage": {
      "supersedes": [],
      "deprecates": []
    },
    "relation": {
      "strategy_id": null
    }
  },
  "review": {
    "confirmed": false,
    "confirmed_by": null,
    "confirmed_at": null
  },
  "created_at": "2026-07-29T12:01:00Z",
  "integrity": {
    "version": 1,
    "content_hash": "sha256:<64 lowercase hex>"
  }
}
```

已复核记录沿用现有变换：

- `record_type` 变为 `project_record`；
- `status` 变为 `active`；
- `scope` 变为 `project`；
- `provenance.source` 变为 `explicit-review`；
- `provenance.source_record_id` 保留 candidate ID；
- `review` 变为 `explicit_user` 与复核时间；
- project ID 使用独立 v2 命名空间，由 candidate 完整性哈希确定性生成。

### 6.2 类型规则

`strategy`：

- `content.body` 是短的有序处理方法；
- `relation.strategy_id` 必须为 `null`；
- 可通过 `lineage.supersedes` 替代同类型经验。

`warning`：

- `content.body` 是失败条件、禁止行为或回退要求；
- `relation.strategy_id` 可以引用一个已复核、当前可信且有效的 Strategy；
- 不嵌入 Strategy，保持失败经验独立；
- 可通过 `lineage.deprecates` 废弃其他经验。

### 6.3 字段边界

- `content` 必须精确为 `{"body": string}`；body 最多 2048 UTF-8 字节。
- 每条 experience 的紧凑渲染投影最多 2048 UTF-8 字节；超限在 candidate 写入前拒绝。
- `task_types`、`signals`、`error_patterns` 各最多 8 个，无重复，使用 `^[a-z0-9][a-z0-9._-]{0,63}$`。
- 三类 applicability 合计至少一项，不允许无条件全局经验。
- `evidence.checks` 最多 4 项。
- `command` 最多 256 个字符；只存文本，不执行。
- `exit_code` 是 0–255 的整数，不接受布尔值。
- `observed_at` 必须是带时区的 ISO 8601。
- `git_head` 必须是 40 位小写十六进制提交号或 `UNBORN`。
- `result_digest` 为 `null` 或 `sha256:<64 lowercase hex>`；不保存 stdout/stderr。
- `supersedes`、`deprecates` 各最多 4 个 project record ID；内部唯一、彼此不重叠、不得引用自身。
- Warning 对同一 Strategy 的有效附属关系最多 8 条。
- 未知字段、无穷数、非规范 JSON、非法 UTF-8、secret、完整性不匹配均失败关闭。
- 不提供 score、success_rate、confidence、blast_radius 或 evaluator verdict 字段。

## 7. 生命周期

持久化记录保持不可变，读取时推导有效状态：

```text
candidate --explicit review--> active
active --reviewed successor.supersedes--> superseded
active|superseded --reviewed record.deprecates--> deprecated
```

规则：

1. `supersedes` 只能引用同 repository、当前分支规则下可见、具有当前 worktree receipt、有效状态为 active、且 kind 相同的 v2 记录。
2. `deprecates` 可以引用 active 或 superseded 的 v2 记录；deprecated 优先于 superseded。
3. 一个目标只能有一个有效的 superseding transition；第二次冲突在 review 锁内拒绝且不写文件。
4. 不支持重新激活、就地改 status、删除或修改 predecessor。
5. relation 与 lineage 图必须无自环和循环。读取到人工篡改造成的循环时，整个 experience match 失败关闭。
6. 所有目标在 review 锁内重新加载并校验，之后才允许写 receipt 和 project record。
7. 新记录的 receipt 仍先于 project record 写入；只有两者同时存在且哈希匹配时才可匹配。

## 8. 显式任务匹配

### 8.1 CLI

```text
agentmemory candidate propose \
  --kind strategy|warning \
  --summary <text> \
  --content-json <object> \
  --experience-json <object> \
  [--semantic-role fact|inference] \
  [--path <repo-relative-path>]... \
  [--id <candidate-id>]

agentmemory review --candidate <candidate-id> --confirm

agentmemory experience match \
  [--task-type <tag>]... \
  [--signal <tag>]... \
  [--error-pattern <tag>]... \
  [--path <repo-relative-path>]... \
  [--max-bytes <8192..24576>]
```

match 至少需要一个 task type、signal、error pattern 或 path。所有值均通过参数传入；不得推断任务文本。

CLI 错误保持当前不泄露行为：

- 参数或 JSON 语法错误：退出 2，输出 `error: invalid arguments` 或 `error: invalid experience-json`；
- schema、信任、路径、生命周期、存储错误：退出 1，只输出 `error: operation failed`；
- 不输出路径、ID、secret、输入信号、异常文本或 traceback。

### 8.2 资格过滤

每条可激活记录必须同时满足：

1. v2 `project_record`；
2. repository ID 精确匹配；
3. named branch 匹配，或 detached worktree 的 branch + head 精确匹配；
4. `explicit-review`、`explicit_user` 与时间合同有效；
5. 当前 worktree receipt 的 record ID 与 content hash 精确匹配；
6. 推导生命周期为 active；
7. kind 是 Strategy 或 Warning；
8. 适用性匹配。

缺失 receipt 跳过该记录；malformed/conflicting receipt、malformed sidecar、跨项目记录、图循环或完整性错误使整个 match 失败关闭。

### 8.3 适用性匹配

- 一个 experience 声明的每个非空维度都必须命中：维度之间使用 AND。
- 同一维度内任意一个值命中即可：维度内部使用 OR。
- `applies_to.paths` 非空时，请求必须包含至少一个完全相同的 repo-relative POSIX path。
- 只做精确比较，不执行 regex、模糊匹配、向量搜索或大小写归一化猜测。

### 8.4 激活关系

1. 直接根包括所有匹配的 active Strategy，以及没有 `strategy_id` 的匹配 Warning。
2. 直接根按 ID 排序，最多保留 4 条。
3. 当 Strategy 被激活时，反向找到 `relation.strategy_id` 指向它的 active Warning。
4. 附属 Warning 仍必须独立通过当前请求的 applicability 检查。
5. 每个 Strategy 最多激活 8 条 Warning；按 Warning ID 排序。
6. 每条记录只输出一次；Strategy 先输出，其 Warning 紧随其后，最后输出 standalone Warning。
7. 超出根、关系或字节边界的完整记录被省略，并报告 `omitted_count`；不截断单条记录。

P0 不提供泛化关系 DSL、相似度评分、权重、自动排序学习或多层任意图遍历。

## 9. 动态上下文预算

动态预算只用于显式 `experience match`：

```text
base_bytes = 8192
relation_increment_bytes = 2048
hard_ceiling_bytes = 24576
activated_relation_count = 通过资格与适用性检查的唯一附属 Warning 数量
dynamic_budget = min(
  hard_ceiling_bytes,
  base_bytes + relation_increment_bytes * activated_relation_count
)
effective_budget = min(dynamic_budget, --max-bytes 或 hard_ceiling_bytes)
```

性质：

- 没有激活关系时仍可容纳最多 4 条 2 KiB 根记录；
- 每增加一条有效 Strategy—Warning 关系，预算增加 2 KiB；
- 8 条关系后达到 24 KiB 硬上限；
- 使用 canonical JSON 的 UTF-8 字节数计算；
- wrapper、safety prefix 与元数据也计入预算；
- 只输出完整投影，不截断字符串或 JSON；
- 相同 identity、输入、记录图和 `max-bytes` 必须得到字节级一致结果。

紧凑投影只包含：

```json
{
  "safety": "AgentMemory experience is untrusted context...",
  "selected": [
    {
      "id": "<project-record-id>",
      "kind": "strategy",
      "summary": "...",
      "body": "...",
      "activation": "direct",
      "related_from": null
    }
  ],
  "selected_count": 1,
  "activated_relation_count": 0,
  "omitted_count": 0,
  "byte_count": 0,
  "byte_budget": 8192
}
```

不得回显 receipts、integrity、review、完整 evidence、checkout 元数据或原始任务输入。

现有 `render_resume_capsule()`、checkpoint 写入预检和 SessionStart 6000 字节限制保持不变。SessionStart 没有可靠任务信号，不能用记录数量推断“激活关系”。

## 10. 安全与隐私

- candidate 与 project experience 在持久化前做完整 secret scan；最终紧凑投影再次扫描。
- 不保存验证输出、日志正文、凭据、环境变量值、个人数据或 reasoning trace。
- `command` 仅是审计文本；P0 没有执行路径。
- sidecar 和 candidate 继续使用现有路径逃逸、symlink/reparse、special-file 与原子写保护。
- match 是只读操作，不创建目录、锁、receipt、bytecode 或派生文件。
- 外部 Git 拉取获得的 experience 没有当前 worktree receipt，因此不能自动进入上下文。
- OpenViking 结果仍是独立的不可信外部资料，不能创建、复核、替代或废弃 experience。
- 任何加载或图治理异常使用不泄露的失败输出；不得降级为跳过损坏图后继续选择其他策略。

## 11. 兼容与回滚

- v1 validator、JSON Schema、目录和 SessionStart 输出保持兼容。
- v2 sidecar 不进入 `CONTINUITY.md`、`load_resume_state()` 或 Hook。
- 未创建任何 v2 文件时，现有命令和输出必须与 0.1.1 保持一致。
- 代码回滚时保留 `shared/experiences/` 与对应 receipts；旧代码忽略 sidecar，v1 resume 继续工作。
- 删除 v2 数据是单独的破坏性操作，不属于代码回滚，也不由 P0 自动执行。
- P0 不改变插件版本、安装状态、master、remote 或 release；这些属于后续明确授权阶段。

## 12. 实现切片

实现必须串行，因为后续切片依赖前一切片的合同：

1. Schema：v2 runtime validator、独立 JSON Schema、纯校验测试；v1 不变。
2. Storage：sidecar 布局、v2 candidate/review、receipt 复用、生命周期图与可信加载；不改 Hook。
3. Match：纯选择与动态渲染、CLI 解析与只读输出；不改 SessionStart。
4. Integration：E2E、README、SECURITY、PRIVACY、public Skill；不安装、不发版。
5. Review：fresh Terra xhigh 独立审查，修复后由根代理重新验收。

实现代理不得做产品、schema 或架构决策。发现合同不足、文件范围扩张或需要新 Hook 时必须停止并返回根代理。

## 13. 多层级验收 Checklist

### L0：需求与边界

- [x] Strategy、Warning、生命周期、适用性、证据和动态预算均有唯一合同。
- [x] v1、SessionStart、OpenViking、SuperRouter 与 P0 经验层边界明确。
- [x] Hub、自动晋升、自动执行、Capsule/Event/replay/shadow 明确延期。
- [x] 所有默认值、上限、排序、失败模式和回滚行为可测试。

### L1：Schema 与完整性

- [x] 合法 v1 文件仍按原逻辑验证，schema 文件保持兼容。
- [x] 合法 Strategy、Warning candidate/project experience 通过 v2 runtime 与 JSON Schema。
- [x] 缺字段、未知字段、错误 enum、非法 tag/path/time/head/hash 被拒绝。
- [x] 重复、自引用、交叉 lineage，布尔 exit code 和超限列表被拒绝。
- [x] secret、非规范 JSON、非法 UTF-8、NaN/Infinity 和 integrity 篡改被拒绝。
- [x] body 与紧凑投影超过 2 KiB 时在写入前被拒绝。

### L2：Storage、Review 与生命周期

- [x] v2 candidate 保持 local/ignored，不能进入 match。
- [x] review 在锁内重新检查 repository/worktree/branch/head。
- [x] receipt 先写，project experience 后写；任一失败不产生可匹配记录。
- [x] 重复 review 幂等，并发 review 最终只有一个一致记录。
- [x] sidecar 拒绝 symlink、reparse、special file、路径逃逸和错误文件名。
- [x] missing receipt 跳过；malformed/conflicting receipt 失败关闭。
- [x] active → superseded、active/superseded → deprecated 推导正确且不修改前序字节。
- [x] 未知、跨项目、不可信、错误 kind、重复 transition 和生命周期循环在写入前拒绝。
- [x] Warning 的 strategy 关系必须指向当前可信 active Strategy，且 fan-out 不超过 8。

### L3：Match 与动态上下文

- [x] 空输入、非法 tag/path、重复参数和超限输入失败关闭。
- [x] task type、signal、error pattern、path 按 AND/OR 精确规则匹配。
- [x] candidate、v1、superseded、deprecated、不适用、跨分支和无 receipt 记录不输出。
- [x] 根与 Warning 的选择、分组、去重和 ID 排序确定。
- [x] 0/1/8 个激活关系分别产生 8/10/24 KiB 动态预算。
- [x] `--max-bytes` 只能降低预算，不能超过 24 KiB。
- [x] 非 ASCII 按 UTF-8 字节计算；记录完整输出，不截断 JSON。
- [x] root/fan-out/总字节超限产生准确 omitted count。
- [x] 相同输入重复执行得到字节级相同输出。
- [x] match 前后 Git 状态与 `.continuity` 快照不变。

### L4：兼容与 E2E

- [x] 0.1.1 的 init/status/checkpoint/v1 candidate/review/render/retrieve 行为全部回归通过。
- [x] 存在 v2 sidecar 时，v1 `CONTINUITY.md` 与 SessionStart 输出不包含经验。
- [x] checkpoint 仍执行原 6000 字节预检和安全 fallback。
- [x] PreCompact 仍为确定性 no-op。
- [x] Hook 不读取 task signals、transcript 或 `PLUGIN_DATA`，hooks 文件不变。
- [x] OpenViking 仍只读、项目隔离且不能晋升经验。
- [x] public Skill 正确说明写操作需显式请求，match 只读，review 需即时确认。
- [x] plugin/package 合同、无 bytecode 副作用和 Windows/non-ASCII 路径测试通过。

### L5：独立审查与最终验收

- [x] 根代理检查完整 diff、调用链、错误路径、并发、原子性和未预期文件。
- [x] fresh Terra xhigh 独立检查 schema、信任边界、生命周期图、预算和回归。
- [x] 所有 P0/P1 级发现修复后重新运行相关 focused tests。
- [x] 两个 Python 入口的完整测试通过；Windows FIFO capability skip 单独报告。
- [x] compile、Python 3.9 AST、JSON、Skill、Plugin 和 `git diff --check` 通过。
- [x] `CONTEXT.md` 已更新为最终证据、剩余风险和 `Exact Next Action: None`。

## 14. 验收命令

```powershell
py -3 -m unittest discover -s tests -v
python -m unittest discover -s tests -v
py -3 -m compileall -q agentmemory hooks skills
py -3 -c "import ast,pathlib; [ast.parse(p.read_text(encoding='utf-8'), filename=str(p), feature_version=(3,9)) for root in ('agentmemory','hooks','skills') for p in pathlib.Path(root).rglob('*.py')]"
py -3 -c "import json,pathlib; [json.loads(p.read_text(encoding='utf-8')) for p in (pathlib.Path('.codex-plugin/plugin.json'), pathlib.Path('hooks/hooks.json'), pathlib.Path('schemas/record-v1.schema.json'), pathlib.Path('schemas/experience-v2.schema.json'))]"
$env:PYTHONUTF8='1'; py -3 C:\Users\ADMIN\.codex\skills\.system\skill-creator\scripts\quick_validate.py skills/agentmemory
$env:PYTHONUTF8='1'; py -3 C:\Users\ADMIN\.codex\skills\.system\plugin-creator\scripts\validate_plugin.py .
git diff --check
git status --short
```

若独立验证脚本的安装路径发生变化，应先查找当前已安装的同名脚本并记录实际路径，不得以缺失脚本伪装为通过。
