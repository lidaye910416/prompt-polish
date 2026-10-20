---
name: flow
description: 把选定的提示词改写成一份能交给 Workflow 编排器、扇出多个 agent 的任务规格（workflow-spec/v1），含线性 stages、每 stage 的扇出形态、每项的真 JSON Schema、汇总与验证规则。Use when the user wants a rough prompt turned into a multi-agent orchestration spec — keywords 润色, 改写成 workflow, 编排, 多 agent, 扇出, fan-out, orchestrable spec, polish for workflow. Not for /goal completion conditions (that is the goal skill).
argument-hint: "[原文 | @文件]"
allowed-tools: Bash(pbpaste), Bash(pbcopy), Bash(cat *), Bash(grep *), AskUserQuestion
---

# 模式2：润色成 Workflow 编排规格

## 这个模式在做什么

产出一份 `workflow-spec/v1`——**规格，不是可运行的 JS**。运行时的 Claude 拿着它、面对真实仓库和当前 budget，把它编译成 `pipeline()` / `parallel()` 脚本。

为什么不让本模式直接吐 JS：

1. `meta` 必须是 PURE LITERAL（不能写 `phases: WORK_ITEMS.map(...)`），生成 JS 就得在润色时刻把工作清单烤死进 `meta`——而清单恰恰是润色阶段还不知道的东西，方向反了。
2. 中文里的 `` ` ``、`${`、``` 围栏拼进模板字符串必断。本机 12 个真实 workflow script 全是 `agent(\`${COMMON}...${w.prompt}\`)` 这个形态。
3. 规格 + 脚本 = 两份真相，改一份就漂移。

**字段顺序 = 执行顺序**，所以 Claude 的编译退化成填空，不是翻译。规定顺序，而不是生成代码。

<!-- 共享块 v1 · mode=flow — 改这里必须同步改 skills/goal/SKILL.md 的同名块 -->

## 1. 取原文（三路，依次尝试）

1. 有参数 → 直接用参数（`$ARGUMENTS` 逐字保留换行、引号、反引号）
2. 无参数但输入以 `@` 开头 → `cat` 该路径
3. 都没有 → `pbpaste`

三者皆空则打印用法后退出，**不要 pbcopy**。

## 2. 幂等

产物第一行固定：`<!-- polished-by: prompt-polish mode=flow v1 -->`

输入已含此行 → **不重写、不碰剪贴板**，只输出「已符合 v1 规格，差异如下：」+ 逐条差异。
没有这个标记，模型无法区分「待润色的原始需求」和「我上次吐的 spec」，结果是 spec 外面再包一层 spec。

## 3. 语言镜像

输出语言 = 输入语言。**YAML 的 key 固定英文**（机器消费，下游脚本按 key 取值），**value 跟随输入语言**。

## 4. 改写规则

- **保留用户原话里的每一条祈使/否定句**（要/必须/不要/禁止/先…再…/别/未经允许不要），**逐字搬运**，搬进 `non_goals` 或对应 work item 的 prompt。
- **不发明用户没提的需求。** 唯一合法的四种填空：目标文件路径 / 技术栈 / 测试命令 / 验收阈值。
- **形容词 → 可观察动作。** 黑名单：`优化 完善 改进 提升 更好 合理 优雅 高效 简洁 干净 清晰 健壮 稳定 成熟 最佳 完美 流畅 全面 彻底 深入 系统性地 梳理 治理 收敛 尽量 尽可能 适当 酌情 视情况 建议 尝试 探索` / `clean elegant idiomatic robust scalable optimal better properly correctly thoroughly polished comprehensive sensible reasonable appropriate seamless`
- **规模自适应**：输入本身是单人可完成的动作 → 见 §7 降级。输入已隐含多角度（"调研"、"全面审查"、"对比几种方案"）才走本模式。

<!-- /共享块 -->

## 5. 输出：`workflow-spec/v1`

单个 yaml 围栏块，第一行版本标记。

````
<!-- polished-by: prompt-polish mode=flow v1 -->
```yaml
# workflow-spec/v1

goal: |                     # 一句话目标
shared_brief: |             # ≤200 字；编排器必须【逐字】prepend 到每个 work item，禁止 agent 自行重建背景
non_goals:                  # inline 进每一个 work item
  - 不做架构重构
  - 不改 API 契约

args:                       # 全局；same script + same args → 100% cache hit
  as_of: "2026-10"          # 沙箱无 Date.now()/Math.random()，时间截止必须显式传
  coverage_cap: 18

phases: [枚举, 深读, 汇总, 对抗校验]   # 与编排器 meta.phases[].title 和 phase(title) 逐字一致

stages:                     # 线性 stage 链（不用 DAG，见 §6）
  - name: 枚举
    shape: parallel         # parallel | pipeline
    items:
      - id: scan-oss        # → opts.label；也是去重键 + journal 定位键
        effort: low         # → agent({effort})
        isolation: worktree # → agent({isolation})，仅当该 item 会写文件
        prompt: |           # → agent() 第一参数，必须自包含
        schema:             # → agent({schema})，真 JSON Schema：根 type:'object'，required ⊆ properties
          type: object
          properties: { items: { type: array, items: { type: object } } }
          required: [items]
  - name: 深读
    shape: pipeline
    items: [...]

verification:
  mode: adversarial         # none | judge-panel | adversarial
  lenses: [正确性, 可复现性]
  pass_rule: 至少 1 个 lens 判 REFUTED/UNCERTAIN → 该断言降级为「未经证实」，从报告中移除

stop_conditions:            # 计数型，不是时间型
  - 合并后候选清单为空 → 立即返回 {report_md: "未找到", items: []}，跳过后续阶段
  - 候选清单 > coverage_cap → 取前 N，并 log(`丢弃 ${n} 个：${names}`)；静默截断视为规格违规

budget: {agents_max: 40}    # → budget.remaining() 守卫 + 静态规模公式

output:                     # → 脚本 return 的形状
  report_md: string
  dropped_count: number     # 被截断丢弃的条目数；>0 时必须在报告末尾声明
```
````

## 6. 字段准入规则

**每个字段要么直接映射到一个 Workflow 原语，要么是编排器必须逐字 inline 进 agent prompt 的文本。两者都不满足 → 删。**

**只用线性 `stages`，不用 DAG。** 运行时只有两个组合原语：`pipeline`（线性 stage、逐 item 独立、stage 间无 barrier）和 `parallel`（barrier）。带 fan-in 的 DAG（A→C、B→C）在这两个原语里**不可表达**——写成 DAG 只会让 Claude 悄悄线性化，静默丢掉全部并行度。所以 `depends_on` 这个字段**不存在**，stage 之间就是线性推进。

**明确不收的字段**：逐 item 的 `model`（强制编排器二次判断一个本该继承的值；文档原话 "Default to omitting it"）、逐 item 的 `agentType`（把 agent 注册表泄漏进规格）、`timeline` / `milestones` / `owner` / `risk` / `rollback` / `persona` / `tone` / `success_metrics`（折叠进 `stop_conditions`）、`code_skeleton` / `template`、`open_questions`（折叠进 `stop_conditions` 第一条：非空即 `blocked_on`，不要开跑，先问用户）。

## 7. 硬禁令：反引号

**产物正文内不得出现** `` ` ``、`${`、或 ``` 三反引号。需要嵌套代码块一律用 `~~~`。字段值需要引号就用中文引号或 `「」`，不要用 ASCII 双引号包裹含 `${` 的内容。

复制前自检：

```bash
printf '%s' "$SPEC" | grep -n '`\|\${\|```' && echo "有反引号族字符，修掉再复制"
```

## 8. 单人任务降级

识别：估算出的 work item ≤1，或输入动词是单人可完成的动作（改个 typo、调个参数、补一行日志）。

行为：**输出模式1 的产物**（照 `skills/goal/SKILL.md` §5 的骨架构造），前置一行说明：

```
这个任务不需要扇出（估算 work item = 1），已降级为 /goal 格式。
```

**不输出 yaml 规格**。避免「把一句话膨胀成八段文档」——执行者读 60 行才发现要做一件事。

## 9. 复制并回复

```bash
printf '%s' "$SPEC" | pbcopy
```

只回一行：

```
已复制 N 字到剪贴板（workflow-spec/v1）。下一步：让 Claude 照这份规格编译成 Workflow 脚本。
```
