# prompt-polish 插件设计规格

- 日期：2026-10-19
- 状态：待 review
- 目标产物：`~/.claude/skills/prompt-polish/`，以 `prompt-polish@skills-dir` 加载

---

## 1. 要解决的问题

用户有一段提示词（中文为主），想让它变成两种东西之一：

- **模式 1（goal）**——一条能直接粘到 Claude Code 内置 `/goal` 命令后面、让 Claude 自主干到底直到可验证完成的条件串。
- **模式 2（flow）**——一份能交给 Workflow 编排器、扇出多个 agent 的任务规格。

两个模式都是**输入一段提示词，输出一段改写后的提示词**。这是本插件的全部职责。

---

## 2. 已验证的外部事实

这一节全部有据可查，是整个设计的地基。任何一条被推翻，设计都要重做。

### 2.1 `/goal` 的真实契约

来源：官方文档 `code.claude.com/docs/en/goal` + 本机 `claude.exe` v2.1.295 二进制字符串交叉验证。`/goal` 于 v2.1.139 引入。

| 事实 | 证据 |
|---|---|
| `/goal <condition>` 收的是**完成条件**，不是任务指令；设置后立即以该条件为指令开始一轮工作 | 二进制命令注册：`{type:"local-jsx", name:"goal", description:"Set a goal Claude checks before stopping", argumentHint:"[<condition> \| clear]"}` |
| 实现是**会话级 prompt-based Stop hook**：每轮结束后把条件 + transcript 交给一个**独立的 evaluator 模型**（小快模型），返回 met / not_met / impossible | CHANGELOG + evaluator prompt 原文 |
| **evaluator 不跑命令、不读文件，只读对话 transcript** | 官方文档原文；evaluator prompt 要求 `<quote evidence from the transcript>` |
| 证据不足时的默认答案是 `insufficient evidence in transcript` | evaluator prompt 末句原文 |
| 条件硬上限 **4000 字符** | 二进制 `var lRt=4000`，报错 `Goal condition is limited to ${lRt} characters` |
| 规范化时 tab 按 8 展开（计算长度时） | 报错文案 `... characters once canonicalized for display (tabs expand to spaces)` |
| 失败态：`goal_check_timeout` / `goal_check_capped` / `goal_interruption` / `goal checks kept finding it unmet this turn`；**没有 stall 保护**，空转几轮后循环停止但 goal 仍是 set 状态 | 二进制字符串 |
| 子命令：`/goal`（状态面板）、`/goal clear`（别名 clear/stop/off/reset/none/cancel，忽略大小写） | 二进制字符串 |

**结论：模式1 的目标不是"写一份更好的提示词"，而是"写一份 transcript 检查清单"。** 缺证据条款 → 必然空转到 `goal_check_capped`；缺禁止缩范围条款 → 静默假绿。两条都必须写死进输出串。

### 2.2 Claude Code hook 的能力边界

| 事实 | 证据 | 对设计的影响 |
|---|---|---|
| `UserPromptSubmit` hook 的输出 schema 只有 `hookEventName` + `additionalContext` | 二进制 schema；全二进制 `updatedPrompt` 命中 **0** 次 | **hook 不可能改写提示词**。模式必须由用户显式调用 |
| 没有选区 API | 全二进制 `selectedText` / `selected_text` / `editorSelection` 命中 **0** 次 | "选定的提示词"只能通过粘贴或 `pbpaste` 进入 |
| 多个插件的同名 hook 独立注册、全部执行、`additionalContext` 拼接 | 本机 `codegraph prompt-hook`（settings.json 内）与 prompt-improver 自动发现的 hook 同时生效 | 保留 prompt-improver 不会崩，只是语义对抗 |
| `UserPromptSubmit` hook 超时后 `additionalContext` 被**静默丢弃**，不报错 | 机制审查结论 | 不能把核心逻辑放进 hook |
| 插件命令带 namespace 前缀（`/plugin:skill`）；`~/.claude/skills/` 下的用户 skill 裸调用 | 本会话可用 skill 列表实证：`ponytail:ponytail`、`prompt-improver:prompt-improver`、`claude-hud:setup` 均带前缀；`agent-reach`、`pdf`、`docx` 等裸调用 | 调用形态是 `/prompt-polish:goal` |
| `claude plugin init <name>` 脚手架落在 `~/.claude/skills/<name>/`，自动以 `<name>@skills-dir` 加载 | 隔离 HOME 实测 | 目录位置由此确定 |
| `claude plugin init --with` 可选组件：skills / agents / hooks / mcp / lsp / output-style / channel（**没有 commands**） | `claude plugin init --help` 实测 | 模式入口走 skill，不走 command |
| 脚手架产物：`.claude-plugin/plugin.json`（含 `"skills": ["./"]`）+ 根 `SKILL.md` + `skills/example/SKILL.md` | 隔离 HOME 实测 | 结构照此改 |
| 多个 Skill 可共享 `references/*.md` | 已装 prompt-improver 即如此 | 见 §5 关于不抽共享文件的决定 |

### 2.3 Workflow 编排原语

设计模式2 规格时**只能用**这些原语：

```
agent(prompt, {label, phase, schema, model, effort, isolation, agentType})
pipeline(items, stage1, stage2, ...)   // 线性 stage，逐 item 独立，stage 间无 barrier
parallel([...thunks])                  // barrier，等齐所有
args / budget{total, spent, remaining} / log() / phase()
```

约束：并发上限 `min(16, cpus-2)`；agent 总数上限 1000；单次调用最多 4096 项；沙箱 JS 无 `Date.now()`、无 `Math.random()`、无 fs、无 Node API；`meta` 必须是 **PURE LITERAL**。

**`depends_on` 不是原语**——把二进制内嵌的 Workflow 工具描述（27,538 字符）整段抽出，`depends_on` 出现 **0** 次。只有 `pipeline`（线性）和 `parallel`（barrier）两个组合原语，**带 fan-in 的 DAG 不可表达**。因此模式2 规格不声明 DAG，改用线性 `stages`。

### 2.4 已装的 prompt-improver@claude-community 0.6.1

已启用（`~/.claude/settings.json` → `enabledPlugins`）。三个 hook（`UserPromptSubmit` / `PreToolUse` / `SubagentStart`）各跑一次 `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/engine.py <Event>`。

- **纯声明式规则引擎**，529 行 Python（engine 186 + rules 183 + nudge_builtins 160），全 stdlib，零 LLM 调用
- 规则是 `nudges/<Event>/*.json`，两种形态：`action`（criteria + text 纯数据）/ `handler`（`improve`、`workflow` 两个 Python 函数）
- **输出能力只有 `inject_context` 一种**（`rules.py` 的 `CAPABILITY_MATRIX` 写死），`block`/`permissionDecision` 是未实现的 future type
- **永远 exit 0**：规则抛异常只往 stderr 打一行然后跳过
- `UserPromptSubmit` 的 6 条规则里，**`improve`（p0）和 `plan-mode`（p50）无条件触发**；其余 4 条是正则门，且全是 `\b` 锚定的英文词
- Python `re` 里 CJK 字符算 word character，`\b` 在中英交界处不成立 → **中文提示词下 4 条关键词门实测全哑**（`用一个workflow编排多agent` 不匹配，`修复 workflow 文件` 匹配，因为后者 `workflow` 前后有空格）
- 每轮实测注入：中文提示词 2 段，约 287 tok
- **不测质量**：104 个 pytest 函数全测引擎形状和 skill 结构，无一条测"润色得好不好"

**决策：留着共存**（用户拍板）。技术上零冲突（本插件不带任何 hook，不进 `UserPromptSubmit` 链路）；代价是每轮 ~287 tok 和两条语义对抗的常驻指令（`improve` 说"模糊就提 1-6 个澄清问题"、`plan-mode` 说"复杂就先进 plan mode"），与模式1"不要问，把判据写死"的设计方向相反。用户已知悉并接受。

---

## 3. 决策记录

| # | 决策 | 依据 |
|---|---|---|
| D1 | 做成插件，目录 `~/.claude/skills/prompt-polish/` | 用户拍板。`claude plugin init` 官方位置，自动以 `prompt-polish@skills-dir` 加载；有 manifest 和版本号 |
| D2 | prompt-improver 留着共存 | 用户拍板。零技术冲突 |
| D3 | 模式2 只出 YAML 规格，不生成可运行 JS | 用户拍板。理由：`meta` 必须 PURE LITERAL，生成 JS 会在润色时刻把工作清单烤死进 `meta`——而清单恰恰是润色阶段还不知道的东西，方向反了；且中文里的反引号 / `${` / ``` 围栏拼进模板字符串必炸 |
| D4 | 模式2 遇单人任务自动降级成模式1 + 说明原因 | 用户拍板 |
| D5 | 输入三路全支持：裸调用走 `pbpaste`、带参数、`@文件` | 用户拍板 |
| D6 | 产物 `pbcopy` 进剪贴板，回复一句话确认 + 字数 | 用户拍板 |
| D7 | 两个 SKILL.md，共享的 15 行故意复制粘贴 | 见 §5 |
| D8 | 幂等标记行插在产物第一行 | 一个标记同时解决模式1 二次润色、模式2 规格套娃、v1/v2 兼容判断 |
| D9 | 不带任何 hook | §2.2：hook 改不了提示词 + 会跟 prompt-improver 抢事件 + 超时静默丢上下文 |
| D10 | frontmatter 不钉 `model:` | 润色是纯改写任务，先用会话模型；等有实测数据再定 |

---

## 4. 文件布局

```
~/.claude/skills/prompt-polish/
├── .claude-plugin/
│   └── plugin.json          {name, version, description, skills:["./"]}
├── skills/
│   ├── goal/
│   │   └── SKILL.md         模式1，约 90 行
│   └── flow/
│       └── SKILL.md         模式2，约 140 行
└── scripts/
    └── check.py             模式1 确定性校验，约 55 行，纯 stdlib
```

无根 `SKILL.md`（脚手架会生成一个，这里不需要——两个子 skill 就是入口）。
无 `hooks/`、无 `references/`、无 `evals/`（v2 再考虑）。

安装：
```bash
claude plugin init prompt-polish --with skills --description "..."
# 删掉脚手架生成的 skills/example/，按上表建目录
/reload-plugins
```

装完用 `/plugin` 核一次实际调用名（预期 `/prompt-polish:goal` 和 `/prompt-polish:flow`）。

---

## 5. 两个 SKILL.md 共享的 15 行（故意复制）

| # | 规则 |
|---|---|
| S1 | **取原文**：有参数用参数；无参数用 `pbpaste`；两者皆空则打印一行用法后退出。`@文件` 先展开再走上面两条 |
| S2 | **幂等标记**：产物第一行固定 `<!-- polished-by: prompt-polish mode=<goal\|flow> v1 -->`。输入已含此行 → 不重写，只输出「已符合 v1 规格」+ 逐条差异，且**不碰剪贴板** |
| S3 | **语言镜像**：输出语言 = 输入语言（中文进中文出，英文进英文出，中英混合以需求句主体语言为准） |
| S4 | **保留用户原话里的每一条祈使/否定句**（要/必须/不要/禁止/先…再…/别/未经允许不要），逐字搬运，不改写语气。这是重写时最容易蒸发的东西 |
| S5 | **不发明用户没提的需求**。唯一合法的四种填空：目标文件路径 / 技术栈 / 测试命令 / 验收阈值。其余一律进 `假设` 段 |
| S6 | **形容词 → 可观察动作**。黑名单命中即替换（见 §6.4） |
| S7 | **输出即消息本体**，可直接粘贴。无前言、无「以下是润色后」 |
| S8 | **提问类输入**（疑问句、无终态）原样返回 + 一句「这是提问不是任务，未做润色」，不硬造目标 |

**为什么不抽成 `references/core.md`**：15 行不值得多一层间接层，而且跨 skill 引用 `${CLAUDE_PLUGIN_ROOT}` 在 SKILL.md 正文里能否替换**未经验证**（只在 `hooks.json` 的 command 字段里验证过）。复制粘贴是确定的。**升级触发条件**：共享部分增长到 50 行以上时，改为共享文件。

---

## 6. 模式1 契约（`/prompt-polish:goal`）

### 6.1 输入

| 形态 | 行为 |
|---|---|
| `/prompt-polish:goal`（无参数） | `pbpaste` 读剪贴板 |
| `/prompt-polish:goal <文本>` | 直接用参数（`$ARGUMENTS` 逐字保留换行/引号/反引号） |
| `/prompt-polish:goal @file` | 展开文件后同上 |

剪贴板为空 / 非文本 → 打印用法后退出，**不 pbcopy**（覆盖空剪贴板是破坏性的）。

### 6.2 输出骨架

```markdown
<!-- polished-by: prompt-polish mode=goal v1 -->
目标：<一句话终态。动词开头；每个名词带绝对路径/数量/grep 计数/退出码；结尾带一条兼容性承诺>

范围：
1) <一行一步，动宾开头，写清产物落到哪个文件>
2) …

约束：
- 禁止<用户原话里的红线，逐字搬运，不润色>
- 禁止修改任何已有测试的期望值
- 禁止通过删除或跳过测试（skip/xit/xfail）、放宽断言、降低覆盖率或阈值、注释掉报错、
  删除本任务要求产出的文件、git checkout/stash 回滚来满足本条件；出现任一即视为未完成
- 禁止执行 git push、gh pr merge、rm -rf、发布、发送消息、删数据等对外或不可逆操作，
  除非本条件明确写出且用户已在对话中确认
- 禁止顺手改动本任务无关的代码；看到无关问题只在对话里提一句，不要动手
- <至少一条路径级禁令：不得改动某目录/某文件>

验收（在 <仓库绝对路径> 下逐条运行；把每条命令与其完整原始输出原样贴进对话，不摘要、不节选）：
1. `<可运行命令>` → 退出码 0 且输出含 `N passed`
2. `<可运行命令>` → 退出码 0 且输出含 `0 failed`
3. `git diff --name-only -- tests/` → 无输出
4. `<可运行命令>` → 退出码 0（连续跑 4 次全绿，排除抖动测试）

证据格式（逐字照抄，禁止改写、截断、翻译、保留 ANSI 颜色码；粘贴前用 NO_COLOR=1 重跑）：
===验收输出=== <该条命令的 stdout+stderr 纯文本原文> exit=0 ===/验收输出===
没有这段输出即视为未完成。代码写完但没跑、没贴不算完成；「已修复」「我认为已解决」
「应该没问题了」「测试通过了」都不构成证据。

完成=【验收】每条命令的结果与标注一致且原始输出已贴进本对话；【约束】中「禁止」类条目
逐条确认未违反；【范围】逐项写「已做/未做 + 证据」，未做的必须写出来。部分完成不算完成。
任一条不满足就继续做，不要停下来汇报进度。若同一判据在通过与失败之间来回翻转，
停止修改并贴出冲突的两个输出与共同根因。

上限：12 轮。遇阻不提问、不等我回复，按影响最小的假设继续并在回复首行写明 `假设：…`。
第 12 轮仍不满足就立即停止一切工具调用，输出「已完成项：编号+证据 / 未完成项：编号+卡在
哪一步+为什么 / 阻塞原因与人工解锁命令」三段后停止，不要继续重试。
```

**六个标签为什么活下来**（每个都对着"只读 transcript 的盲判定器"审过）：

| 标签 | 存在理由 |
|---|---|
| `目标` | 唯一的判定对象。没它，判定器不知道 `ok:true` 指什么 |
| `范围` | 逐项匹配 transcript 里的专有名词；扇出任务里这是唯一能识破"只做了 1/4"的结构 |
| `约束` | 给 `ok:false` 一个可引用的理由 |
| `验收` | 命令字符串是可搜锚点，行尾 `→` 标注让判定器能把"命令 + 声称结果"配对 |
| `证据格式` | 唯一把"我完成了"翻译成"记录里有可引用文本"的东西。**整个模板的杠杆点，删了必空转** |
| `完成=` | 自指【验收】而不重述，是最大的压缩杠杆（朴素写法 +800 字）；同时告诉判定器哪些条目之间是 AND |
| `上限` | 唯一的防死循环条款。软性上限（"尽快"）等于无界烧钱 |

**删掉什么**：背景/动机（不改变判定结果）、实施步骤与技术选型（计划不是终态）、风险缓解、时间估算、参考链接清单（判定器不能 fetch）、独立的"完成定义"段（已被 `验收` + `完成=` 吸收）。

### 6.3 字符预算

| 段 | 预算 | 压缩优先级 |
|---|---|---|
| 目标 | 200 | 永不砍 |
| 范围 | 600 | 最先砍 |
| 约束 | 300 | 中（已被验收命令覆盖的条目先删） |
| 验收 | 500 | 永不砍 |
| 证据格式 | 220 | 永不砍 |
| 完成= | 180 | 永不砍 |
| 上限 | 150 | 永不砍 |
| **合计** | **~2150** | 余量 1850 留给用户改写 |

压缩技术：自指替代重述、路径替代内容、验收即结构（一行一条命令 + 行尾标注）、约束用否定祈使句、单层 `cd`（头部写绝对路径，命令里不重复）、把否定约束翻译成可执行断言（"禁止引入新依赖" → `grep -rniE "^(import|from) (click|typer|rich)" src/ tests/` → 无输出）。

**超限处理**：拒绝，不截断，也不"压缩后重试一次"。截断会正好砍掉末尾的 `完成=` 和 `上限`，判定器只剩一句任务描述，必然每轮 `not_met`；静默重写会让用户不知道贴到剪贴板的是哪一版。

### 6.4 禁用词

- **必删**：`优化 完善 改进 提升 更好 合理 优雅 高效 简洁 干净 清晰 健壮 稳定 成熟 最佳 完美 流畅 全面 彻底 深入 系统性地 梳理 治理 收敛 尽量 尽可能 适当 酌情 视情况 建议 尝试 探索` / `clean elegant idiomatic best-practices robust scalable maintainable production-ready optimal better improved properly correctly thoroughly nicely smoothly polished comprehensive sensible reasonable appropriate high-quality seamless`
- **结构性禁写**：裸尖括号 `<>`（反引号内合法）、`{{...}}` 模板残留、`TODO` `待填` `xxx` `占位`、模糊指代（"那个项目""这块代码""相关文件"）
- **会诱发作弊的措辞**：单说"测试通过"而不带"贴出测试输出"；"代码写好了"；"应该可以了"；把 `范围` 的编号当完成条件（纯自证）
- **不可判定绝对式**：`零告警` `完全没有输出` `绝对无` `没有任何注释` `100% 覆盖` → 一律改写为可数形式

### 6.5 check.py

跑在 `pbcopy` **之前**，从 stdin 读待复制串。exit 0 才允许复制。

| 退出码 | 检查 | 理由 |
|---|---|---|
| 2 | 空输入 | 不 pbcopy（覆盖空剪贴板是破坏性的） |
| 2 | 首字符是 `/` 或 `@` | 否则粘贴后被当成别的命令或 `@file` 展开 |
| 2 | 规范化后长度 > 4000 | `var lRt=4000`；规范化照 `/goal` 口径（`\r\n`→`\n`、逐行 `rstrip()`、`expandtabs(8)`、首尾 `strip()`），宁可早失败 |
| 1 | 六个标签各出现且只出现一次 | 两个矛盾的定义 = 判定器无从下手。正则 `(?m)^{标签}[^\n]{0,80}[：:]`（允许 `验收（在 /path 下…）：` 这种长括注） |
| 1 | `(?m)^完成\s*=` 恰好一次 | 同上 |
| 1 | 验收段编号条目数 == 带 `→` 标注的条目数 | 判定器要能把"命令 + 声称结果"配对 |
| 1 | 范围段至少 1 条编号 | 扇出任务里唯一能识破"只做了 1/4"的结构 |
| 1 | `(?m)^上限[：:]\s*\d+\s*轮` | 软性上限等于无界烧钱 |
| 1 | 必含子串 `贴`、`exit=`、`禁止` | 分别守证据强制、机器味 token、防作弊 |
| 1 | 反引号外的文本不含禁用形容词 | 引号内是可搜锚点，放行 |

反引号外的判定方式：`bare = re.sub(r"\`[^\`]*\`", "", s)`，再在 `bare` 上跑禁用词正则。

**输出**：exit 2 → 中文错误信息到 stderr，不 pbcopy；exit 1 → 中文错误信息到 stderr，不 pbcopy；exit 0 → 静默，调用方执行 `pbcopy`。

### 6.6 拒绝策略

**分支 A —— 输入根本不是任务**（空、纯提问、"你好"、"帮我想想 X 好不好"）：

> 这不是一个可执行的任务，无法生成 /goal 条件。/goal 的判定器只看对话里有没有出现能引用的证据，它判断不了"好不好""够不够"，会一直判成未达成然后反复续跑。
> 请补三样：①要改的文件或目录（绝对路径）②一条能判定成败的命令（如 npm test / pytest / tsc --noEmit）③不允许改动的范围。
> 补齐后再运行 /polish-goal。

原文照抄，不生成任何 `/goal` 串，**不 pbcopy**。纯粹的"不行"是失败的转介，所以必须给出可执行的下一步。

**分支 B —— 是任务但推不出检查**（输入 1–20 字，如"修一下那个 bug"）：**默认照润不追问**，因为要求贴输出，猜错的检查跑不出输出，判定器在 transcript 里看得见，模型下一轮会自己换命令——这是自愈的。但必须显式化假设，并把可运行性兜底写进验收段：

> 现状：先读 <用户给的路径> 确认真实代码结构，把确认结果写进对话再动手；不要凭猜测改文件。
>
> 若上述验收命令在当前环境跑不通（缺凭据、断网、服务未启动、缺依赖），不得判为"不可完成"：先执行并贴出依赖安装 / 构建 / 环境探测的真实输出，再改用离线可执行的等价检查，并把替代命令与理由一并贴出。禁止以"无法执行""环境不行"作为结束理由。

**输入含不可逆操作**（push/merge/rm/发布/删）：不拒绝，改写成四步门控（dry-run 清单 → 备份并贴出备份输出 → 执行 → 复核并贴出前后计数），强制加不可逆禁令，回复里加一行：

> ⚠ 本条件含不可逆操作，已加入禁止条款并改为"备份成功才执行"。请确认后再粘贴。

---

## 7. 模式2 契约（`/prompt-polish:flow`）

### 7.1 输出：`workflow-spec/v1`

单个 yaml 围栏块，第一行版本标记（自己的 eval 能断言格式，将来改版也能提示用户"升级你的旧规格"）。

```yaml
# workflow-spec/v1

goal: |                     # 目标，一句话
shared_brief: |             # ≤200 字；编排器必须【逐字】prepend 到每个 work item，禁止 agent 自行重建背景
non_goals:                  # inline 进每一个 work item
  - 不做架构重构
  - 不改 API 契约

args:                       # 全局；same script + same args → 100% cache hit
  as_of: "2026-10"          # 沙箱无 Date.now()，时间截止必须显式传
  coverage_cap: 18

phases: [枚举, 深读, 汇总, 对抗校验]   # 与 meta.phases[].title 和 phase(title) 逐字一致

stages:                     # 线性 stage 链（不用 DAG——见 §2.3）
  - name: 枚举
    shape: parallel         # parallel | pipeline
    items:
      - id: scan-oss        # → opts.label；也是去重键 + journal 定位键
        effort: low         # → agent({effort})
        isolation: worktree # → agent({isolation})，仅当该 item 会写文件
        prompt: |           # → agent() 第一参数
        schema:             # → agent({schema})，必须是真 JSON Schema：根 type:'object'，required ⊆ properties
          type: object
          properties: { items: { type: array, items: { type: object } } }
          required: [items]
  - name: 深读
    shape: pipeline
    items: [...]

verification:               # → 追加的 pipeline stage / judge panel / 对抗轮次
  mode: adversarial
  lenses: [正确性, 可复现性]
  pass_rule: 至少 1 个 lens 判 REFUTED/UNCERTAIN → 该断言降级为"未经证实"，从报告中移除

stop_conditions:            # 计数型，不是时间型
  - 合并后候选清单为空 → 立即返回 {report_md: "未找到", items: []}，跳过后续阶段
  - 候选清单 > coverage_cap → 取前 N，并 log(`丢弃 ${n} 个：${names}`)；静默截断视为规格违规

budget: {agents_max: 40}    # → budget.remaining() 守卫 + 静态规模公式

output:                     # → 脚本 return 的形状
  report_md: string
  dropped_count: number     # 被截断丢弃的条目数；>0 时必须在报告末尾声明
```

### 7.2 字段准入规则

**每个字段要么直接映射到一个 Workflow 原语，要么是编排器必须逐字 inline 进 agent prompt 的文本。两者都不满足 → 删。**

**明确不收的字段**：逐 item 的 `model`（强制编排器二次判断一个本该继承的值；文档原话 "Default to omitting it"）、逐 item 的 `agentType`（把 agent 注册表泄漏进规格）、`timeline` / `milestones` / `owner` / `risk` / `rollback` / `persona` / `tone` / `success_metrics`（折叠进 `stop_conditions`）、`code_skeleton` / `template`、`open_questions`（折叠进 `stop_conditions` 第一条：非空即 `blocked_on`）。

### 7.3 为什么不出可运行 JS（D3 的完整理由）

1. `meta` 必须 PURE LITERAL——不能写 `phases: WORK_ITEMS.map(...)`，只能整体内联数组，而工作清单恰恰是润色阶段还不知道的东西。生成 JS 强制在润色时刻把清单烤死，方向正好搞反。
2. 用户的中文提示词里出现 `` ` ``、`${`、`\` 是日常操作，unescaped 拼进 JS 模板字面量轻则语法错误重则字符串注入。规格是散文，装得下。
3. 只有一份真相。规格 + 脚本 = 两份，改一份就漂移。编译这个活在运行时的 Claude 手里做得更好——它面前有仓库、有文件列表、有当前 budget，润色阶段这些都没有。

用"规格即脚本大纲"化解"规格太啰嗦"：**字段顺序 = 执行顺序**，Claude 的编译退化成填空，不是翻译。**规定顺序，而不是生成代码。**

### 7.4 硬禁令：反引号

产物正文内**不得出现**反引号、`${`、或 ``` 三反引号。需要嵌套代码块一律用 `~~~`。字段值需要引号就用中文引号或 `「」`，不用 ASCII 双引号包裹含 `${` 的内容。

理由：本机 12 个真实 workflow script 全是 `` agent(`${COMMON}...${w.prompt}`, ...)`` 这个形态，中文里一个反引号就断。不写这条，第一次编译就炸。

### 7.5 单人任务降级（D4）

识别：估算出的 work item 数 ≤ 1，或输入动词是单人可完成的动作（改个 typo、调个参数、补一行日志）。

行为：**输出模式1 的产物**，前置一行说明：

> 这个任务不需要扇出（估算 work item = 1），已降级为 /goal 格式。

**不 pbcopy 模式2 规格**。避免"把一句话膨胀成八段文档"——执行者读 60 行才发现要做一件事。

### 7.6 幂等

产物第一行 `<!-- polished-by: prompt-polish mode=flow v1 -->`，紧跟 yaml 围栏。输入已含此行 → 不重写，只输出「已符合 v1 规格」+ 逐条差异，且不碰剪贴板。

这解决"把产物再喂回去会套娃"：没有这个标记，模型无法区分"待润色的原始需求"和"我上次吐的 spec"。

---

## 8. 明确不做（non-goals）

| 不做 | 理由 |
|---|---|
| 任何 hook | `UserPromptSubmit` 改不了提示词；会跟 prompt-improver 抢同一次事件；超时静默丢上下文 |
| 历史 / 撤销 / 版本管理 | 本插件不保存任何历史、不修改任何原文。原文在用户自己的终端里，**撤销 = 不粘贴** |
| 自动自评分循环（润色→打分→重润） | v1 不做。先手用两次再说 |
| 生成可运行 Workflow JS | D3 |
| 逐 item 的 `model` / `agentType` | §7.2 |
| 钉死 frontmatter `model:` | D10 |
| marketplace 发布 | 单人自用 |
| `evals/` 套件 | v2。`claude plugin eval` 已验证存在且支持 skills-dir 插件，但先手用 |
| 语言检测 / 双语模板分叉 | 模型本身就可靠地跟随输入语言，语言路由层是伪装成规则的规则引擎 |

---

## 9. 验收标准

做完后用 `/goal` 跑这一条（同时也是本插件的 dogfood）：

```
插件装在 ~/.claude/skills/prompt-polish/，以 prompt-polish@skills-dir 加载，
提供 /prompt-polish:goal 和 /prompt-polish:flow 两个 skill。

满足以下全部即为完成，每条都要把命令的真实输出贴进对话：
1. claude plugin details prompt-polish@skills-dir 列出 2 个 skill
2. printf '目标：x\n范围：\n1) y\n约束：\n- 禁止z\n验收：\n1. `true` → 退出码 0
   证据格式：===验收输出=== exit=0 ===/验收输出===\n完成=全部贴出\n上限：3 轮' \
   | python3 ~/.claude/skills/prompt-polish/scripts/check.py
   → 退出码 0
3. 同一条输入去掉「证据格式」段 → 退出码 1 且 stderr 提示缺证据条款
4. 构造 4001 字符的输入 → 退出码 2 且 stderr 报超上限
5. echo '/goal x' | claude -p '把这条改写成 /goal 条件' 退出码 0，
   输出含 6 个标签且 ≤4000 字符 —— 把输出原样贴出
6. claude plugin disable prompt-polish@skills-dir 之后 /reload-plugins，
   /prompt-polish:goal 不再出现在 skill 列表

约束：不动 ~/.claude/settings.json 里已有的任何 hook（prompt-improver 保持启用）；
不修改 ~/.claude/skills/ 下其它任何 skill；不 commit、不 push 任何东西。
不做：README、marketplace 发布、evals 套件、hooks。
或 stop after 12 turns。
```

第 2–4 条是 `check.py` 的最小自检，**不依赖任何 LLM 判断**，跑一次就知道逻辑没坏。

---

## 10. 未验证项 / 风险

| 项 | 状态 |
|---|---|
| `/prompt-polish:goal` 的实际调用名 | **推断**自本会话 skill 列表实证的命名空间规则（插件 skill 带 `plugin:skill` 前缀）。装完必须用 `/plugin` 核一次 |
| `${CLAUDE_PLUGIN_ROOT}` 在 SKILL.md 正文里能否替换 | **已证实可替换**（2026-10-20 查官方文档）：正文 markdown 与 `allowed-tools` 里的 Bash 规则都会展开，可让 skill 免批准跑自带脚本。原「不跨 skill 共享文件」的规避已不需要 |
| `disable-model-invocation: true` 在本机是否生效 | 文档里有，未在本机任何 SKILL.md 上实证过。v1 不用它 |
| 两个 SKILL.md 各自独立演化导致的漂移 | 已知代价。缓解：共享块在两个文件里都标注 `# 共享块 v1 — 改这里必须同步改另一个`，涨到 50 行时抽文件 |
| `pbcopy` 覆盖用户剪贴板里原有的无关内容 | 已接受（D6）。若输入来自 `pbpaste` 则无损失；若来自 `@文件` 则会覆盖 |

---

## 11. 实现顺序（进 writing-plans 后展开）

1. `claude plugin init prompt-polish --with skills`，删脚手架产物，按 §4 建目录
2. 写 `scripts/check.py` + 一个 assert 自检（§9 第 2–4 条就是它的测试）
3. 写 `skills/goal/SKILL.md`（模板 + 15 行共享块 + 拒绝策略 + 幂等）
4. 写 `skills/flow/SKILL.md`（workflow-spec/v1 + 降级 + 硬禁令 + 幂等）
5. 12 条中文 fixture 手工跑一遍，对照 §6.2 骨架逐条核对
6. `git init ~/.claude/skills/prompt-polish/` 并提交（**只在用户明确要求时 push**）
7. 用 §9 的 `/goal` 条件跑一次终验
