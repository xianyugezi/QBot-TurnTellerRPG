"""统一发送出口 Sender 单测（M4 批次1·路B2 · qbot_rpg/commands/sender.py）。

依据：m4_shared_contract §2.2（页码非法 → TPL-12 + 错误模板统一 + emoji 纪律 + segment_by_length）
     + 细化_3a §5.3（壳层发送职责：CQ 转义 / 长度预算分条 / 失败重试 + 风控退避 / 禁止裸 send）
     + 细化_3d §五（TPL-12/13/14 统一文案 D-04）/ §5.1（原指令片段 20 字符截断）
     + 2026-08-27 用户裁决②（0/负数/非数字页码 → TPL-12 报错）。

覆盖：segment_by_length 分条（4000 字上限/不吞内容）· cq_escape 防注入 · TPL-12 统一文案 +
20 字符截断 · TPL-13/TPL-14 一句式 · 页码非法 → TPL-12 + 页脚（裁决②）· Sender 发送流程
（转义→分条→逐条）· 失败重试指数退避 / 重试耗尽抛错 · 缺省收集模式 · emoji 纪律（TC-18）。
"""
from __future__ import annotations

import pytest

from qbot_rpg.commands.errors import TPL_ERR_BAD_COMMAND, TPL_ERR_CONDITION, TPL_ERR_LACK_RESOURCE
from qbot_rpg.commands.sender import (
    BACKOFF_BASE,
    DEFAULT_LENGTH_BUDGET,
    MAX_RETRIES,
    Sender,
    SenderSendError,
    cq_escape,
    format_tpl12,
    format_tpl13,
    format_tpl14,
    page_error_tpl12,
    segment_by_length,
)

# 3d §4.2 装饰性 emoji 禁用清单
BANNED = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"


# ---------------------------------------------------------------------------
# segment_by_length（QQ 4000 字分片，3a S5 / 规则 L507）
# ---------------------------------------------------------------------------

def test_default_budget_is_qq_4000():
    """QQ 单条文本上限 4000 字（对齐 3a §5.3；超长分两条发送）。"""
    assert DEFAULT_LENGTH_BUDGET == 4000


def test_segment_short_text_single():
    assert segment_by_length("你好") == ["你好"]
    assert segment_by_length("a" * 4000) == ["a" * 4000]  # 恰好 = 预算 → 单条


def test_segment_long_text_no_loss():
    """超长分条：顺序不颠倒、不吞内容（拼接 == 原文）。"""
    text = "字" * 4001
    segs = segment_by_length(text)
    assert len(segs) == 2
    assert "".join(segs) == text
    assert len(segs[0]) == 4000 and len(segs[1]) == 1


def test_segment_three_chunks():
    text = "A" * 9001
    segs = segment_by_length(text)
    assert [len(s) for s in segs] == [4000, 4000, 1001]
    assert "".join(segs) == text


def test_segment_empty():
    assert segment_by_length("") == []


def test_segment_budget_invalid():
    with pytest.raises(ValueError):
        segment_by_length("x", budget=0)
    with pytest.raises(ValueError):
        segment_by_length("x", budget=-5)


# ---------------------------------------------------------------------------
# cq_escape（防注入，框架 L1622 / 规则 L510）
# ---------------------------------------------------------------------------

def test_cq_escape_basic():
    assert cq_escape("a&b[c]d") == "a&amp;b&#91;c&#93;d"


def test_cq_escape_blocks_cq_injection():
    """正文无法拼出伪造 [CQ: 段（S2 + 防注入）。"""
    out = cq_escape("[CQ:at,qq=123]")
    assert "[CQ:" not in out
    assert "&#91;CQ:" in out


def test_cq_escape_idempotent_safe():
    """转义结果再次转义：& 先转义，顺序稳定（&#91; 中的 & 也会被二次转义——CQ 转义预期行为）。"""
    assert cq_escape("&[]") == "&amp;&#91;&#93;"
    assert cq_escape(cq_escape("&[]")) == "&amp;amp;&amp;#91;&amp;#93;"


# ---------------------------------------------------------------------------
# 错误模板统一 TPL-12/13/14（3d §五 D-04：唯一文案源 errors.py，一句式禁止自造三要素）
# ---------------------------------------------------------------------------

def test_tpl12_exact_text():
    """TC-20 对应：指令出错统一文案逐字。"""
    assert format_tpl12("/攻撃") == "❌ 指令不正确：/攻撃。输入 /帮助 查看可用指令。"
    # 文案与唯一源常量一致（未自造变体）
    assert format_tpl12("x") == TPL_ERR_BAD_COMMAND.format(fragment="x")


def test_tpl12_truncate_20_chars():
    """3d §5.1：原指令片段截取前 20 字符，超过加 …。"""
    long_frag = "/" + "长" * 30
    out = format_tpl12(long_frag)
    assert out == TPL_ERR_BAD_COMMAND.format(fragment="/" + "长" * 19 + "…")
    assert "长" * 20 not in out


def test_tpl13_exact_text():
    """TC-21 对应：条件不满足统一文案（可读中文条件名 + 双方数值必填）。"""
    assert format_tpl13("锻造等级", "2 级", "5 级") == "❌ 条件不满足：锻造等级（当前 2 级，需要 5 级）"
    assert format_tpl13("n", 2, 5) == TPL_ERR_CONDITION.format(name="n", current=2, required=5)


def test_tpl14_exact_text():
    """TC-22 对应：资源不足统一文案（唯一源 errors.py 模板 `{resource}{amount}` 无空格）。"""
    assert format_tpl14("金币", 500, 120) == "❌ 资源不足：需要 金币500，当前 120"
    assert format_tpl14("r", 1, 0) == TPL_ERR_LACK_RESOURCE.format(resource="r", amount=1, current=0)
    # 3d §5.3 示例「需要 金币 500」（带空格）由调用方传 amount=" 500" 达成
    assert format_tpl14("金币", " 500", 120) == "❌ 资源不足：需要 金币 500，当前 120"


def test_page_error_tpl12_invalid_page():
    """裁决②：0/负数/非数字页码 → TPL-12 统一报错 + 页脚 TPL-08 指引（不静默兜底页）。"""
    out = page_error_tpl12("/背包 0", "背包", 3, 14)
    assert "❌ 指令不正确：/背包 0。输入 /帮助 查看可用指令。" in out
    assert out.split("\n")[-1] == "— 第 1/3 页 · 共 14 条 · 输入 /背包 页码 翻页 —"


def test_page_error_tpl12_uses_canonical_source():
    """页码报错文案来自唯一源 errors.py 常量（3d D-04），非本模块自造。"""
    assert page_error_tpl12("/商店 abc", "商店", 2, 9).startswith(
        TPL_ERR_BAD_COMMAND.format(fragment="/商店 abc")
    )


# ---------------------------------------------------------------------------
# Sender 发送流程（转义 → 分条 → 逐条）
# ---------------------------------------------------------------------------

def _make_sender(recorder, **kw):
    """注入 send_text 回调并收集调用。"""
    def send_text(text, *, to=None):
        recorder.append((text, to))
    return Sender(send_text, retry_sleep=lambda _: None, **kw)


def test_send_segments_and_escape():
    """CQ 转义 → 长度分条 → 逐条发送，返回发送成功段列表（顺序不颠倒）。"""
    calls = []
    s = _make_sender(calls)
    long_text = "字" * 4001
    delivered = s.send(long_text, to="group1")
    assert len(delivered) == 2
    assert [len(t) for t, _ in calls] == [4000, 1]
    assert "".join(t for t, _ in calls) == long_text  # 不吞内容
    assert all(to == "group1" for _, to in calls)


def test_send_escapes_cq_injection_before_send():
    calls = []
    s = _make_sender(calls)
    s.send("hi [CQ:at,qq=1]")
    assert calls[0][0] == "hi &#91;CQ:at,qq=1&#93;"  # 发送侧恒为转义后文本


def test_send_short_single_and_to_propagation():
    calls = []
    s = _make_sender(calls)
    delivered = s.send("你好", to="g1")
    assert delivered == ["你好"] and calls == [("你好", "g1")]


def test_sender_default_recorder_mode():
    """缺省 send_text（无平台环境）：记录到 delivered 属性，可直接断言。"""
    s = Sender(retry_sleep=lambda _: None)
    delivered = s.send("第1段" + "字" * 4000, to="g1")
    assert delivered == s.delivered
    assert len(delivered) == 2 and "".join(delivered) == "第1段" + "字" * 4000


def test_send_retry_then_success_with_backoff():
    """失败重试 + 指数退避：先失败 2 次再成功 → 重试 2 次，睡眠 2 秒、4 秒。"""
    calls = []
    sleeps = []

    def flaky(text, *, to=None):
        calls.append(text)
        if len(calls) <= 2:
            raise RuntimeError("网络抖动")
    s = Sender(flaky, retry_sleep=sleeps.append)
    s.send("ok")
    assert len(calls) == 3  # 原始 1 次 + 重试 2 次
    assert sleeps == [BACKOFF_BASE ** 1, BACKOFF_BASE ** 2]  # 2.0, 4.0


def test_send_retry_exhausted_raises():
    """重试耗尽仍失败 → SenderSendError（不无限重发，规则 L503/L523）。"""
    def always_fail(text, *, to=None):
        raise RuntimeError("boom")
    sleeps = []
    s = Sender(always_fail, retry_sleep=sleeps.append, max_retries=MAX_RETRIES)
    with pytest.raises(SenderSendError):
        s.send("x")
    assert len(sleeps) == MAX_RETRIES  # 只退避 MAX_RETRIES 次，不无限


def test_send_retry_after_first_failure_continues_rest():
    """多段时某段重试成功不吞后续段（顺序不颠倒）。"""
    calls = []
    sleeps = []
    fail_once = {"n": 0}

    def flaky(text, *, to=None):
        if fail_once["n"] == 0:
            fail_once["n"] += 1
            raise RuntimeError("first drop")
        calls.append(text)
    s = Sender(flaky, retry_sleep=sleeps.append)
    delivered = s.send("AA" + "B" * 4000)  # 4002 字 → 2 段
    assert len(delivered) == 2
    assert calls == ["AA" + "B" * 3998, "BB"]  # 第 1 段首试失败→重试成功，第 2 段正常
    assert sleeps == [2.0]


def test_sender_invalid_config():
    with pytest.raises(ValueError):
        Sender(max_retries=-1)
    with pytest.raises(ValueError):
        Sender(backoff_base=0)


# ---------------------------------------------------------------------------
# emoji 纪律（TC-18）
# ---------------------------------------------------------------------------

def test_error_templates_emoji_discipline():
    """错误文案仅 ✅/❌ 功能性标记，无装饰 emoji（3d §四 D-01）。"""
    outs = [
        format_tpl12("/x"),
        format_tpl13("等级", 1, 5),
        format_tpl14("金币", 500, 0),
        page_error_tpl12("/背包 0", "背包", 2, 9),
    ]
    for out in outs:
        assert not any(ch in out for ch in BANNED)
        assert "✅" not in out  # 失败场景只有 ❌
        assert out.startswith("❌ ")
