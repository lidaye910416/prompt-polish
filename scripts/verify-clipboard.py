#!/usr/bin/env python3
"""Assert the clipboard currently holds a valid prompt-polish artifact.

This is the acceptance test for the plugin's output contract: after
/prompt-polish:goal (or :flow) finishes, the polished string — not the reply,
not the raw input — must be sitting in the macOS clipboard, ready to paste.

    /reload-plugins  →  Cmd+C 原文  →  /prompt-polish:goal  →  然后跑这个

    python3 scripts/verify-clipboard.py [goal|flow]

Exit 0 = pass, 1 = fail. Reads the clipboard; never writes it.
"""
import re
import subprocess
import sys

MODE_MARKERS = {"goal": "mode=goal", "flow": "mode=flow"}

# Labels may carry a parenthetical before the colon (「验收（在 /path 下逐条运行；…）：
# 」is the normal shape), so match the same way check.py does rather than literally.
GOAL_LABELS = ["目标", "范围", "约束", "验收", "上限"]
FLOW_FIELDS = ["# workflow-spec/v1", "goal:", "shared_brief:", "stages:", "items:", "stop_conditions:"]


def clipboard():
    out = subprocess.run(["pbpaste"], capture_output=True, text=True)
    return out.stdout


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "goal"
    if mode not in MODE_MARKERS:
        print(f"用法: {sys.argv[0]} [goal|flow]", file=sys.stderr)
        return 1

    text = clipboard()
    print(f"剪贴板 {len(text)} 字符\n" + "-" * 60)

    failures = []

    marker = MODE_MARKERS[mode]
    if marker not in text:
        failures.append(f"没找到幂等标记「{marker}」——剪贴板里不是润色产物")

    if mode == "goal":
        missing = [
            label
            for label in GOAL_LABELS
            if not re.search(rf"(?m)^{label}[^\n]{{0,80}}[：:]", text)
        ]
        if missing:
            failures.append(f"缺段落 {missing}")
        if not re.search(r"(?m)^完成\s*=", text):
            failures.append("缺【完成=】行")
    else:
        missing = [f for f in FLOW_FIELDS if f not in text]
        if missing:
            failures.append(f"缺字段 {missing}")

    if mode == "goal":
        n = len(text)
        if n > 4000:
            failures.append(f"{n} 字符，超过 /goal 上限 4000")
        if not re.search(r"(?m)^上限[：:]\s*\d+\s*轮", text):
            failures.append("没有数字轮次上限")
        if "exit=" not in text:
            failures.append("没有证据格式段（exit= token）")

    if mode == "flow":
        hits = re.findall(r"`|\$\{|\n```", text)
        if hits:
            failures.append(f"产物正文出现反引号族字符 {len(hits)} 处——编译成 JS 会断")

    if failures:
        print("FAIL")
        for f in failures:
            print(f"  ✗ {f}")
        print("\n剪贴板前 200 字：\n" + text[:200])
        return 1

    print(f"PASS — 剪贴板里是一份合法的 mode={mode} 产物\n")
    print("下一步：敲 /goal（或让 Claude 照规格编译 Workflow 脚本）然后 Cmd+V")
    return 0


if __name__ == "__main__":
    sys.exit(main())
