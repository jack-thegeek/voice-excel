"""语音文本解析：提取序号 + 算式，并计算分数。

支持示例：
  "2号，100-2-8等于几"      -> 序号=2, 算式=100-2-8, 结果=90
  "二号 一百减二减八等于多少" -> 序号=2, 算式=100-2-8, 结果=90
  "5号 87.5分"              -> 序号=5, 算式=87.5, 结果=87.5
  "3号 90加5等于几"          -> 序号=3, 算式=90+5, 结果=95
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ---------- 中文数字 -> 阿拉伯数字 ----------
_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

def _cn2num(s: str) -> int:
    """解析一个中文数字片段（支持 0-999，如 十二=12, 二十=20, 一百零五=105）。"""
    s = s.strip()
    if not s:
        raise ValueError("空中文数字")
    # 含"百"
    if "百" in s:
        parts = s.split("百")
        head = parts[0]
        bai = _cn2num(head) if head else 1
        rest = parts[1]
        if not rest:
            return bai * 100
        if rest[0] == "零":
            tail = rest[1:]
            return bai * 100 + (_cn2num(tail) if tail else 0)
        # 如 一百二十
        if "十" in rest:
            shi, *after = rest.split("十")
            shi_val = _cn2num(shi) if shi else 1
            after_val = _cn2num(after[0]) if after and after[0] else 0
            return bai * 100 + shi_val * 10 + after_val
        return bai * 100 + _cn2num(rest)
    # 含"十"
    if "十" in s:
        parts = s.split("十")
        head = parts[0]
        head_val = _cn2num(head) if head else 1
        tail = parts[1] if len(parts) > 1 else ""
        tail_val = _cn2num(tail) if tail else 0
        return head_val * 10 + tail_val
    # 纯个位
    if len(s) == 1 and s in _CN_DIGITS:
        return _CN_DIGITS[s]
    # 多位纯数字（如 "一二三"）逐位
    val = 0
    for ch in s:
        if ch not in _CN_DIGITS:
            raise ValueError(f"无法解析中文数字: {s!r}")
        val = val * 10 + _CN_DIGITS[ch]
    return val


def _tokenize_number(tok: str) -> float:
    tok = tok.strip()
    if not tok:
        raise ValueError("空数字")
    # 全阿拉伯数字（含小数）
    if re.fullmatch(r"\d+(\.\d+)?", tok):
        return float(tok)
    # 含小数点 "X.Y"：两边分别转换（支持中文+阿拉伯混写）
    if "." in tok:
        left, right = tok.split(".", 1)
        if not re.fullmatch(r"\d+", right) and not (right and all(ch in _CN_DIGITS for ch in right)):
            raise ValueError(f"无法识别数字: {tok!r}")
        lv = float(left) if re.fullmatch(r"\d+", left) else float(_cn2num(left)) if left else 0.0
        rv = float(right) if re.fullmatch(r"\d+", right) else (float(_cn2num(right)) if right else 0.0)
        # 右侧作为小数部分：把每一位当独立位（中文"五"=5 → 0.5）
        if not re.fullmatch(r"\d+", right):
            rv = 0.0
            for ch in right:
                rv = rv * 0.1 + _CN_DIGITS[ch] * 0.1
        return lv + rv
    # 全中文数字
    if all(ch in _CN_DIGITS or ch in "百十" for ch in tok):
        return float(_cn2num(tok))
    raise ValueError(f"无法识别数字: {tok!r}")


# ---------- 文本预处理 ----------
_OP_MAP = {
    "加": "+", "加上": "+", "加上去": "+", "再加上": "+",
    "减": "-", "减去": "-", "减掉": "-", "去": "-",
    "乘": "*", "乘以": "*", "乘上": "*",
    "除": "/", "除以": "/", "比": "/",  # "X比Y" 一般不用，这里保守
    # 常见同音/近音字容错：ASR 常把「减/加」听成这些字
    "剪": "-", "件": "-", "见": "-", "简": "-", "间": "-", "建": "-", "坚": "-", "检": "-",
    "家": "+", "佳": "+",
}
# 等于关键词触发"计算模式"
_EQ_MARKERS = ("等于几", "等于多少", "得多少", "得几", "等于啥", "是多少", "是几")


@dataclass
class ParseResult:
    seq: int
    score: float
    expression: str          # 规范化后的算式，如 "100-2-8"
    is_direct: bool          # True=直接给分数(无运算), False=经过运算
    note: str = ""


def parse(text: str) -> ParseResult:
    if not text or not text.strip():
        raise ValueError("空输入")

    raw = text.strip()

    # 1) 提取序号：支持 "2号" / "二号" / "2 号" / "第2号" / "2号同学"
    #    先尝试阿拉伯数字 + 号
    seq_match = re.search(r"(?:第)?\s*(\d+)\s*号", raw)
    if seq_match:
        seq_val = int(seq_match.group(1))
    else:
        # 中文数字 + 号
        m = re.search(r"(?:第)?([零一二三四五六七八九十百〇两]+)\s*号", raw)
        if not m:
            raise ValueError("未识别到序号（应为'N号'或'二号同学'）")
        seq_match = m
        seq_val = int(_cn2num(m.group(1)))

    if seq_val <= 0 or seq_val > 999:
        raise ValueError(f"序号超出合理范围: {seq_val}")

    # 2) 删除序号片段、"同学"、"等于几"等后缀，得到算式部分
    expr_text = raw
    # 去掉序号片段
    expr_text = expr_text[:seq_match.start()] + expr_text[seq_match.end():]
    # 去掉"同学"
    expr_text = expr_text.replace("同学", "")
    # 去掉等于后缀
    for marker in _EQ_MARKERS:
        if marker in expr_text:
            expr_text = expr_text.replace(marker, "")
            break
    # 去掉"分"字（"87.5分"）
    expr_text = expr_text.replace("分", "")
    # 去掉"等于"本身（如果还残留）
    expr_text = expr_text.replace("等于", "")
    # 去掉常见标点（注意：保留小数点 "."）
    for p in "，,。、！？!?,;；":
        expr_text = expr_text.replace(p, " ")

    expr_text = expr_text.strip()
    if not expr_text:
        raise ValueError("未识别到算式或分数")

    # 语音常把小数点念成"点"，如"七十五点五"
    expr_text = expr_text.replace("点", ".")

    # 3) 规范化运算符：中文 -> 符号
    #    按长度从长到短替换
    for cn in sorted(_OP_MAP, key=len, reverse=True):
        expr_text = expr_text.replace(cn, _OP_MAP[cn])
    # 全角运算符
    expr_text = expr_text.replace("＋", "+").replace("－", "-")
    expr_text = expr_text.replace("×", "*").replace("÷", "/").replace("✕", "*")

    # 4) 词法切分：数字 与 运算符 交替
    #    先把符号间用空格分隔
    expr_text = re.sub(r"([+\-*/])", r" \1 ", expr_text)
    tokens = [t for t in expr_text.split() if t]

    if not tokens:
        raise ValueError("算式为空")

    # 解析数字串，识别运算符
    parsed: list = []  # [num, op, num, op, num, ...]
    expect_num = True
    for tok in tokens:
        if expect_num:
            try:
                parsed.append(_tokenize_number(tok))
            except ValueError:
                # 可能是负号开头 "-8" 视作运算符+数字
                if tok in ("+", "-", "*", "/"):
                    raise ValueError(f"算式格式错误：连续出现运算符 {tok}")
                raise
            expect_num = False
        else:
            if tok not in ("+", "-", "*", "/"):
                # 两个数字相邻 -> 当作拼接（罕见）报错
                raise ValueError(f"算式格式错误：缺少运算符，连续数字 {tok}")
            parsed.append(tok)
            expect_num = True
    if expect_num:
        raise ValueError("算式格式错误：以运算符结尾")

    # 5) 计算（左结合）
    if len(parsed) == 1:
        result = float(parsed[0])
        expr_str = _fmt_num(result)
        return ParseResult(seq=seq_val, score=result, expression=expr_str,
                           is_direct=True, note="直接给定的分数")

    result = parsed[0]
    i = 1
    expr_parts = [_fmt_num(result)]
    while i < len(parsed):
        op = parsed[i]
        rhs = parsed[i + 1]
        if op == "+":
            result = result + rhs
        elif op == "-":
            result = result - rhs
        elif op == "*":
            result = result * rhs
        elif op == "/":
            if rhs == 0:
                raise ValueError("除数不能为零")
            result = result / rhs
        expr_parts.append(op)
        expr_parts.append(_fmt_num(rhs))
        i += 2

    expr_str = " ".join(expr_parts)
    # 四舍五入到两位小数，避免浮点尾巴
    result = round(result, 2)
    return ParseResult(seq=seq_val, score=result, expression=expr_str,
                       is_direct=False, note="")


def _fmt_num(x: float) -> str:
    if x == int(x):
        return str(int(x))
    return f"{x:g}"


# ---------- 识别文本归一化（ASR 输出 -> 阿拉伯数字 + 符号） ----------
_CN_NUM_SPAN_RE = re.compile(r"[零〇一二两三四五六七八九十百]+")

# 文本级归一化时要跳过的宽泛单字（否则容易误伤日常词，如"过去/比如"）
_NORM_SKIP_OPS = {"去", "比"}


def _cn_span_to_num(m: "re.Match") -> str:
    """把一段连续中文数字转换为阿拉伯数字；解析失败则原样保留。"""
    try:
        return str(int(_cn2num(m.group(0))))
    except ValueError:
        return m.group(0)


def normalize_text(raw: str) -> str:
    """把 ASR 的中文识别文本归一化为「阿拉伯数字 + 运算符符号」。

    用于后端流式识别结果的实时展示与解析前预处理，让用户直接看到
    「2号 100-2-8 等于几」而不是「二号 一百减二减八 等于几」。
    注意：本函数只做文本层替换，不改语义，最终计算仍由 parse() 完成。
    """
    if not raw:
        return ""
    s = raw
    # 1) 中文数字片段 -> 阿拉伯数字
    s = _CN_NUM_SPAN_RE.sub(_cn_span_to_num, s)
    # 2) 中文运算符 -> 符号（含同音字容错；按长度从长到短，跳过宽泛单字）
    for cn in sorted(_OP_MAP, key=len, reverse=True):
        if cn in _NORM_SKIP_OPS:
            continue
        s = s.replace(cn, _OP_MAP[cn])
    # 3) 全角运算符、小数点的"点"
    s = s.replace("＋", "+").replace("－", "-").replace("×", "*").replace("÷", "/").replace("✕", "*")
    s = s.replace("点", ".")
    return s
