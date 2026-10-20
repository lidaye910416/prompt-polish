# last_session

## 2026-10-19 · prompt-polish v0.1.0 首次实现

### 做了什么

从零建了 `~/prompt-polish/`（仓库根 = 插件根），软链到 `~/.claude/skills/prompt-polish`，
以 `prompt-polish@skills-dir` 加载。三个文件：

- `scripts/check.py` — 模式1 产物的确定性校验器，纯 stdlib，含 `--selftest`（16 条断言）
- `skills/goal/SKILL.md` — 六段输出骨架 + 三路取原文 + 幂等 + 拒绝策略
- `skills/flow/SKILL.md` — `workflow-spec/v1` YAML 规格 + 线性 stages + 反引号硬禁令 + 单人任务降级

`claude plugin details` 实测：Skills (2)、Hooks (0)、always-on ~186 tok。
`claude plugin validate --strict` 通过。

### 关键决策（都是用户拍的板）

| 决策 | 选择 |
|---|---|
| 打包形态 | 真做成 plugin，不是裸 skill |
| 已装的 prompt-improver@claude-community | 留着共存（零技术冲突，每轮 ~287 tok） |
| 模式2 产物 | 只出 YAML 规格，不生成可运行 JS |
| 模式2 遇单人任务 | 自动降级成模式1 + 说明原因 |
| 输入 | 三路全支持：裸调用 pbpaste / 参数 / @文件 |
| 出口 | pbcopy 进剪贴板，回复一句话 + 字数 |

### 下次会话要确认的

- [ ] **实际敲一次 `/prompt-polish:goal`**——本会话里没法调用 slash 命令，`/reload-plugins` 后由用户实测
- [ ] **确认调用名是 `/prompt-polish:goal` 还是别的**——推断自"插件 skill 带 `plugin:skill` 前缀"这条规则，未实证
- [ ] **模式2 产出的规格真能被编译成 Workflow 脚本**——需要拿一个真实任务跑一遍才算数
- [ ] `git push` 未执行（用户未授权），远端无此仓库

### 探测中暴露的两个真缺陷（待修，本轮禁止改判断逻辑故未动）

1. **段标签括注超过 80 字符会被漏检**。`section_count` 用 `^标签[^\n]{0,80}[：:]`，窗口太窄。
   真实润色输出如果把「每条命令在哪跑、怎么贴」写得很长（例如 `验收（在 /Users/jasonlee/某项目 下逐条运行；把每条命令与其完整 stdout+stderr 原始输出逐字贴进对话，不摘要不节选，粘贴前先用 NO_COLOR=1 重跑一遍）：`）就会误报「缺少【验收】段」。
   修法：把窗口从 80 放宽到 200，或改成 `^标签[^\n]*[：:]` 加一个「同行必须有冒号」的兜底。
2. **「完成＝」全角等号不被识别**。`DONE_RE` 只认半角 `=`。中文用户很可能打全角 ＝。
   修法：`DONE_RE = re.compile(r"(?m)^完成\s*[=＝]")`。

两者都只写在 `check.py` 的注释里（`CHINESE_EDGE_CASES` 上方），**没有写成断言**——把 bug 固化成断言等于让它变成契约。

### 踩过的坑（下次别再踩）

1. `check.py` 自检第一次就抓到真 bug：幂等标记 `<!-- polished-by -->` 里的 "polished"
   撞上禁用英文词表。修法是让 `strip_machine()` 连 HTML 注释一起剥掉——标记行是元数据不是散文。
2. 自检的 fixture 自己写错两次（删掉一条 `禁止` 后还剩另一条；tab 断言被 `.strip()` 吃掉）。
   **自检的失败不一定是代码错，先确认 fixture 对不对。**
3. `claude plugin init --with` **不支持 `commands`**，可选项只有
   skills/agents/hooks/mcp/lsp/output-style/channel。所以模式入口只能走 skill。
4. `claude plugin init` 落在 `~/.claude/skills/<name>/`（不是 `~/.claude/plugins/`），
   那里的目录才是官方认的「个人插件」位置。
5. 中文边界用例的期望值必须**先探测再写断言**。第一版凭推断直接写，跑出来挂了两条。
   探测脚本比断言值钱。
6. Edit 改长文件时容易把函数头冲掉——`def selftest():` 连同首个 assert 被一次 Edit 覆盖，
   症状是「后面缩进代码变成孤儿」。改完立刻读一遍改动区间。
