# prompt-polish

把选定的提示词改写成可直接执行的产物。

| 模式 | 入口 | 产物 |
|---|---|---|
| goal | `/prompt-polish:goal` | ≤4000 字符的完成条件串，粘到 `/goal` 后面，Claude 自主干到底 |
| flow | `/prompt-polish:flow` | `workflow-spec/v1` YAML 规格，交给 Workflow 编排器扇出多 agent |

## 安装

```bash
claude plugin marketplace add lidaye910416/prompt-polish
claude plugin install prompt-polish@jasonlee-plugins
```

会话内一条命令（Claude Code 2.1.275+）：

```
/plugin install prompt-polish --marketplace lidaye910416/prompt-polish
```

> macOS only：读写剪贴板用 `pbcopy` / `pbpaste`。

## 用法

复制提示词，然后：

```
/prompt-polish:goal
```

回复「已复制 N 字到剪贴板」后，敲 `/goal` 再 Cmd+V。

也支持带参数和文件：

```
/prompt-polish:goal 把博客的图片都压缩一下
/prompt-polish:goal @~/notes/prompt.md
```

产物进剪贴板，不进对话正文。

## 设计要点

`/goal` 的 evaluator 只能读对话 transcript，不跑命令也不读文件，证据不足时返回 `insufficient evidence in transcript`。所以 goal 模式优化的不是措辞：

1. 每条判据写成 evaluator 能引用来判「没做到」的具体对象
2. 强制主模型把验收命令的原始输出逐字贴进对话
3. 写死轮次上限

flow 模式同理，规格只用线性 `stages`：Workflow 只有 `pipeline`（无 barrier）和 `parallel`（barrier），带 fan-in 的 DAG 不可表达，写了会被静默线性化。

完整设计依据：[`docs/design.md`](docs/design.md)。

## 开发

`check.py` 是唯一有真正逻辑的部分，纯 stdlib：

```bash
python3 scripts/check.py --selftest     # 16 条断言
```

产物流向验收（`PASS` = 剪贴板里是合法产物：幂等标记、六段齐全、≤4000 字符、有轮次上限和 `exit=` 证据 token）：

```bash
python3 scripts/verify-clipboard.py goal   # flow 模式换成 flow
```

本地开发用软链，改完 `/reload-plugins`：

```bash
ln -s "$(pwd)" ~/.claude/skills/prompt-polish
```

## 许可

[MIT](LICENSE)
