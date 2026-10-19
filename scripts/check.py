#!/usr/bin/env python3
"""Mode-1 output validator for the prompt-polish plugin.

Reads the candidate /goal condition from stdin. Exit codes:
  0  pass, silent — caller may pbcopy
  1  fail, Chinese reason on stderr — caller must NOT pbcopy
  2  refuse (empty / wrong first char / over the 4000-char cap)

The length cap and the canonicalization mirror Claude Code's own /goal parser:
CRLF -> LF, strip trailing whitespace per line, expand tabs to 8 columns, trim.
Failing early is deliberate — a string that /goal would reject must never reach
the clipboard.

    python3 check.py < candidate.md
    python3 check.py --selftest
"""
import re
import sys

MAX_LEN = 4000  # /goal hard cap; the CLI reports "Goal condition is limited to 4000 characters"

SECTIONS = ["目标", "范围", "约束", "验收", "上限"]  # must appear exactly once each
DONE_RE = re.compile(r"(?m)^完成\s*=")  # must appear exactly once

TERMINATORS = ["证据格式", "完成", "目标", "范围", "约束", "验收", "上限"]
ITEM_RE = re.compile(r"(?m)^\d+[.)、]")
ARROW_RE = re.compile(r"(?m)^\d+[.)、][^\n]*→")
BOUND_RE = re.compile(r"(?m)^上限[：:]\s*\d+\s*轮")

# 必含子串：分别守「证据强制」「机器味 token」「防作弊」
REQUIRED_SUBSTRINGS = ["贴", "exit=", "禁止"]

# 禁用形容词。判定在剥掉反引号内容之后进行——引号内是可被 evaluator 搜到的锚点，放行。
BANNED = re.compile(
    r"优化|完善|改进|提升|更好|合理|优雅|高效|简洁|干净|清晰|健壮|稳定|成熟|最佳|完美|流畅"
    r"|全面|彻底|深入|系统性地|梳理|治理|收敛|尽量|尽可能|适当|酌情|视情况|建议|尝试|探索"
    r"|\b(?:clean|elegant|idiomatic|robust|scalable|optimal|better|improved|properly|correctly"
    r"|thoroughly|nicely|smoothly|polished|comprehensive|sensible|reasonable|appropriate|seamless)\b"
)
PLACEHOLDERS = re.compile(r"TODO|待填|待补充|占位|\?\?\?|xxx", re.IGNORECASE)


def canonicalize(raw):
    """Normalize the way /goal does before counting characters."""
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip().expandtabs(8) for line in text.split("\n")).strip()


def fail(code, msg):
    print(msg, file=sys.stderr)
    return code


def section_count(text, label):
    """How many lines start with this section label and reach a colon within 80 chars.

    The 80-char window is what lets 「验收（在 /path 下逐条运行；…）：」 pass.
    """
    return len(re.findall(rf"(?m)^{label}[^\n]{{0,80}}[：:]", text))


def block(text, start, terminators):
    """Return the section body from `start` up to the next section label."""
    pat = rf"(?ms)^{start}[^\n]*[：:][^\n]*\n(.*?)(?=^(?:{'|'.join(terminators)})[^\n]*[：:]|\Z)"
    match = re.search(pat, text)
    return match.group(1) if match else ""


def strip_machine(text):
    """Drop the two machine-readable spans so the banned-word check only sees prose.

    Backticks hold quoted evidence (searchable anchors — legal). HTML comments
    hold the idempotency marker (metadata, not prose). Both would otherwise trip
    the banned-word list on their own vocabulary.
    """
    return re.sub(r"<!--.*?-->", "", re.sub(r"`[^`]*`", "", text), flags=re.DOTALL)


def check(text):
    """Return None on pass, or an exit code + message on failure."""
    if not text:
        return 2, "错误：待复制内容为空。"
    if text[0] in "/@":
        return 2, f"错误：输出串不能以 '{text[0]}' 开头——粘贴到 /goal 后面会被当成另一个命令或 @文件展开，条件会被静默替换。"

    n = len(text)
    if n > MAX_LEN:
        return 2, (
            f"错误：润色结果 {n} 字符，超过 /goal 上限 {MAX_LEN}（超出 {n - MAX_LEN}）。\n"
            "请删减【范围】的细节后重试。/goal 不截断——从尾部砍会正好砍掉【完成=】和【上限】，"
            "评估器会永远判未达成。"
        )

    for label in SECTIONS:
        count = section_count(text, label)
        if count == 0:
            return 1, f"错误：缺少【{label}】段。六个标签必须齐全：{' / '.join(SECTIONS)} + 完成="
        if count > 1:
            return 1, f"错误：【{label}】出现了 {count} 次。两个互相矛盾的完成定义会让评估器无从下手。"

    done = len(DONE_RE.findall(text))
    if done == 0:
        return 1, "错误：缺少【完成=】行。"
    if done > 1:
        return 1, f"错误：【完成=】出现了 {done} 次。"

    if not BOUND_RE.search(text):
        return 1, "错误：【上限】未给出具体轮次。「尽快」这类软性上限等于无界烧钱。"

    acceptance = block(text, "验收", ["证据格式", "完成", "上限"])
    items, annotated = len(ITEM_RE.findall(acceptance)), len(ARROW_RE.findall(acceptance))
    if items == 0:
        return 1, "错误：【验收】里没有编号条目。"
    if items != annotated:
        return 1, (
            f"错误：【验收】{items - annotated} 条缺少 → 预期结果标注。"
            "评估器只能读 transcript，它需要把「命令 + 声称结果」配成对才能判定。"
        )

    scope = block(text, "范围", ["约束", "验收", "证据格式", "完成", "上限"])
    if len(ITEM_RE.findall(scope)) == 0:
        return 1, "错误：【范围】里没有编号条目。扇出任务里这是唯一能识破「只做了 1/4」的结构。"

    for needle in REQUIRED_SUBSTRINGS:
        if needle not in text:
            what = {"贴": "证据强制条款", "exit=": "机器味 token", "禁止": "防作弊条款"}[needle]
            return 1, f"错误：缺少「{needle}」（{what}）。缺了它评估器读不到任何可引用的证据，只会一路空转。"

    prose = strip_machine(text)
    hit = BANNED.search(prose)
    if hit:
        return 1, (
            f"错误：反引号外出现不可判定词「{hit.group(0)}」。\n"
            "评估器只能读 transcript，「优化」对它等于没写。改写成「具体对象 + 命令 + 阈值」。"
        )
    hit = PLACEHOLDERS.search(prose)
    if hit:
        return 1, f"错误：残留占位符「{hit.group(0)}」。润色工具不许发明需求，也就不该留下 <待填>。"

    return None


GOOD = """<!-- polished-by: prompt-polish mode=goal v1 -->
目标：tests/auth.py 的登录逻辑覆盖退出码 0，且 auth.py 逐字节不变

范围：
1) 在 tests/auth.py 补 6 条用例：过期 token、锁定账户、空密码、SQL 注入、大小写、并发

约束：
- 禁止修改 auth.py 的任何一行
- 禁止通过删除或跳过测试、放宽断言、降低覆盖率来回滚来满足本条件；出现任一即视为未完成

验收（在 /Users/jasonlee/x 下逐条运行；把每条命令与其完整原始输出原样贴进对话）：
1. `pytest -q tests/auth.py` → 退出码 0 且输出含 `6 passed`
2. `git diff --name-only -- auth.py` → 无输出

证据格式：===验收输出=== <stdout+stderr 原文> exit=0 ===/验收输出===
没有这段输出即视为未完成。代码写完但没跑、没贴不算完成。

完成=【验收】每条命令的结果与标注一致且原始输出已贴进本对话；【范围】逐项写「已做/未做+证据」。

上限：12 轮。遇阻不提问，按影响最小的假设继续并在首行写明 `假设：…`。"""


def selftest():
    """Smallest check that fails if check() breaks. assert-based, no framework."""
    assert check(canonicalize(GOOD)) is None, "canonical sample must pass"

    bad_cases = {
        "empty": ("", 2),
        "slash-leading": ("/goal x", 2),
        "at-leading": ("@file", 2),
        "over-cap": ("目" * 4001, 2),
        "missing-section": (GOOD.replace("范围：\n1) 在", "1) 在"), 1),
        "duplicate-label": (GOOD.replace("目标：", "目标：x\n\n目标：", 1), 1),
        "missing-done": (GOOD.replace("完成=", "完成为", 1), 1),
        "missing-bound": (GOOD.replace("上限：12 轮", "上限：尽快"), 1),
        "no-arrow": (GOOD.replace("→ 退出码 0 且输出含 `6 passed`", "`6 passed`"), 1),
        "no-evidence-token": (GOOD.replace("exit=0", "退出码0"), 1),
        "no-forbid": (re.sub(r"约束：\n(?:- .*\n)+", "", GOOD), 1),
        "banned-word": (GOOD.replace("在 tests/auth.py 补 6 条用例", "优化 tests/auth.py"), 1),
        "placeholder": (GOOD.replace("逐项写「已做/未做+证据」", "逐项写<TODO>"), 1),
        "empty-scope": (GOOD.replace("1) 在 tests/auth.py 补 6 条用例：过期 token、锁定账户、空密码、SQL 注入、大小写、并发\n", ""), 1),
    }
    for name, (raw, want) in bad_cases.items():
        got = check(canonicalize(raw))
        assert got is not None, f"{name}: expected failure {want}, passed"
        assert got[0] == want, f"{name}: expected exit {want}, got {got[0]} ({got[1]})"

    # tab expansion must match /goal: a tab counts as 8 columns, not 1 character.
    # Padded with non-space so the final .strip() can't eat the expansion.
    assert len(canonicalize("a\tb")) == 9, "a tab must expand to 8 columns, not 1 char"
    print(f"selftest: {len(bad_cases) + 2} assertions passed")


def main():
    if "--selftest" in sys.argv:
        return 0 if selftest() is None else 1
    result = check(canonicalize(sys.stdin.read()))
    if result is None:
        return 0
    return fail(result[0], result[1])


if __name__ == "__main__":
    sys.exit(main())
