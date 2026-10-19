# prompt-polish

把一段选定的提示词，改写成两种能直接用的东西。

| 模式 | 入口 | 产物 |
|---|---|---|
| goal | `/prompt-polish:goal` | 一条 ≤4000 字符的完成条件串，粘到 Claude Code 内置 `/goal` 后面，Claude 自主干到底 |
| flow | `/prompt-polish:flow` | 一份 `workflow-spec/v1` YAML 规格，交给 Workflow 编排器扇出多 agent |

设计依据、三条硬事实、字段准入规则、验收标准：[`docs/design.md`](docs/design.md)

## 安装

仓库根就是插件根。已经软链到位了：

```bash
ln -s ~/prompt-polish ~/.claude/skills/prompt-polish
```

改完代码 `/reload-plugins`。开发时也可以不装，直接：

```bash
claude --plugin-dir ~/prompt-polish
```

禁用：`claude plugin disable prompt-polish@skills-dir`。卸载：`rm ~/.claude/skills/prompt-polish`。

## 用法

```bash
# 1. 在任何地方 Cmd+C 复制你的提示词
# 2. 输入框敲：
/prompt-polish:goal
# 3. 回复「已复制 N 字到剪贴板」
# 4. 敲 /goal 然后 Cmd+V 回车
```

也支持带参数和文件：

```
/prompt-polish:goal 把博客的图片都压缩一下
/prompt-polish:goal @~/notes/prompt.md
```

## 为什么不是普通的"提示词润色"

`/goal` 背后有一个独立 evaluator，它**只能读对话 transcript**，不跑命令也不读文件，证据不足时返回 `insufficient evidence in transcript`。所以本模式优化的不是"措辞"，是三件事：

1. 每条判据写成 evaluator 能引用来判「没做到」的具体对象
2. 强制主模型把验收命令的原始输出**逐字贴进对话**
3. 写死轮次上限——没有其他出口，一轮小误会会烧几小时

同理，flow 模式产出的规格只用线性 `stages`：Workflow 运行时只有 `pipeline`（无 barrier）和 `parallel`（barrier），带 fan-in 的 DAG 不可表达，写了会被静默线性化。

## 自检

`scripts/check.py` 是唯一有真正逻辑的部分，纯 stdlib，可以脱离 LLM 单跑：

```bash
python3 scripts/check.py --selftest     # 16 条断言
python3 scripts/check.py < candidate.md # exit 0 才允许 pbcopy
```

## 验收测试：产物真的进剪贴板了吗

这是插件的核心输出契约——`/prompt-polish:*` 跑完后，剪贴板里必须是**润色产物**，不是回复正文，也不是原始输入。

```bash
# 1. 确认剪贴板通路通（应看到 SENTINEL-12345）
printf 'SENTINEL-12345' | pbcopy && pbpaste

# 2. /reload-plugins

# 3. Cmd+C 复制一段提示词，输入框敲：
#    /prompt-polish:goal

# 4. 等回复出来，什么都别碰，另开终端跑：
cd ~/prompt-polish && python3 scripts/verify-clipboard.py goal

# flow 模式换成 flow 参数，并额外检查反引号族字符
python3 scripts/verify-clipboard.py flow
```

`PASS` = 剪贴板里是带幂等标记、六段齐全、≤4000 字符、有数字轮次上限和 `exit=` 证据 token 的合法产物。

失败时会逐条列出原因，并打印剪贴板前 200 字——最常见的失败是「没找到幂等标记」，说明 skill 跑完了但 `pbcopy` 那一步没执行。

## 许可

MIT
