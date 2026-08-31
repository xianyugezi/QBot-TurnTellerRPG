"""M10 钓鱼·批6·路6A：fishing_tpl 模板分区单测（主 agent 收口补齐）。

文件名：tests/unit/test_fishing_tpl.py
创建时间：2026-09-01
作者：Hermes 主 agent（路6A 子 agent 撞迭代上限零落盘，按侦察结论补齐）

覆盖：定稿 §六 消息模板 + M9 模板迁移先例；渲染零 emoji、可覆盖、格式规范。
"""

from __future__ import annotations

import re
from typing import Any, Dict

from qbot_rpg.core.templates import DEFAULT_TEMPLATES, PLACEHOLDER_WHITELIST, tpl_of

_EMOJI_RE = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\uFE0F]")


def _ctx(**kw: Any) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {"templates": dict(DEFAULT_TEMPLATES)}
    ctx.update(kw)
    return ctx


# ---------------------------------------------------------------------------
# 分区 key 齐全（对应指令壳 _render 调用）
# ---------------------------------------------------------------------------
def test_all_fishing_keys_present() -> None:
    """指令壳使用的全部 fish_* key 在分区中。"""
    used_keys = {
        "fish_off", "fish_spot_list_header", "fish_spot_line", "fish_spot_empty",
        "fish_intent_ref", "fish_bite_idle", "fish_bite_waiting", "fish_bite_triggered",
        "fish_reel_bad_choice", "fish_reel_timeout", "fish_reel_stop", "fish_reel_success",
        "fish_codex_header", "fish_codex_summary", "fish_codex_empty",
    }
    missing = used_keys - set(DEFAULT_TEMPLATES)
    assert not missing, f"缺模板 key: {missing}"


def test_all_keys_have_whitelist() -> None:
    """每个 fish_* key 都有白名单条目。"""
    for k in DEFAULT_TEMPLATES:
        if k.startswith("fish_"):
            assert k in PLACEHOLDER_WHITELIST, f"缺白名单: {k}"


# ---------------------------------------------------------------------------
# 渲染正确（占位符替换）
# ---------------------------------------------------------------------------
def test_render_spot_line() -> None:
    """钓点行渲染：占位符替换。"""
    ctx = _ctx()
    out = tpl_of(ctx, "fish_spot_line",
                 {"spot_name": "月光草甸", "periods": "晨/午/昏", "rarity": "普通"})
    assert "月光草甸" in out
    assert "晨/午/昏" in out
    assert "普通" in out


def test_render_bite_triggered() -> None:
    """鱼讯渲染：kind_cn + golden_line。"""
    ctx = _ctx()
    out = tpl_of(ctx, "fish_bite_triggered",
                 {"kind_cn": "猛烈鱼讯", "golden_line": "【金闪】"})
    assert "猛烈鱼讯" in out
    assert "金闪" in out
    assert "收杆" in out


def test_render_codex_summary() -> None:
    """鱼图鉴综述渲染。"""
    ctx = _ctx()
    out = tpl_of(ctx, "fish_codex_summary", {"caught": 3, "king": 2})
    assert "3" in out
    assert "2" in out


def test_render_off() -> None:
    """钓鱼关闭文案。"""
    ctx = _ctx()
    assert tpl_of(ctx, "fish_off", {}) == "钓鱼功能已关闭"


# ---------------------------------------------------------------------------
# 覆盖机制（内容包可覆盖）
# ---------------------------------------------------------------------------
def test_override_by_content_pack() -> None:
    """内容包 templates 覆盖 fish_off。"""
    ctx = _ctx(templates={"fish_off": "本服钓鱼暂未开放"})
    assert tpl_of(ctx, "fish_off", {}) == "本服钓鱼暂未开放"


def test_missing_key_falls_empty() -> None:
    """无该 key → 空串（指令壳回退本地 fallback）。"""
    ctx = _ctx(templates={})
    assert tpl_of(ctx, "fish_nonexistent", {}) == ""


# ---------------------------------------------------------------------------
# 零 emoji（渲染静态断言）
# ---------------------------------------------------------------------------
def test_no_emoji_in_templates() -> None:
    """全部 fish_* 默认模板零 emoji。"""
    for k, v in DEFAULT_TEMPLATES.items():
        if k.startswith("fish_") and isinstance(v, str):
            assert not _EMOJI_RE.search(v), f"模板 {k} 含 emoji: {v}"


def test_no_emoji_in_rendered() -> None:
    """渲染输出零 emoji（含占位符填充后）。"""
    ctx = _ctx()
    samples = [
        tpl_of(ctx, "fish_spot_line", {"spot_name": "湖", "periods": "晨", "rarity": "普通"}),
        tpl_of(ctx, "fish_bite_triggered", {"kind_cn": "微动", "golden_line": ""}),
        tpl_of(ctx, "fish_reel_success", {"kind_cn": "银鳞鲤", "rarity_cn": "普通"}),
        tpl_of(ctx, "fish_codex_summary", {"caught": 1, "king": 1}),
    ]
    for out in samples:
        assert not _EMOJI_RE.search(out), f"渲染含 emoji: {out}"


# ---------------------------------------------------------------------------
# 格式规范
# ---------------------------------------------------------------------------
def test_error_hint_format() -> None:
    """错误提示格式：句号+换行→ 下一步（如 鱼跑了……（收杆超时））。"""
    ctx = _ctx()
    out = tpl_of(ctx, "fish_reel_timeout", {})
    # 以句号/省略号结尾（错误提示规范）
    assert out.endswith("）") or out.endswith("。") or out.endswith("…")


def test_list_line_format() -> None:
    """清单每项独立一行（钓点行以 - 开头）。"""
    ctx = _ctx()
    out = tpl_of(ctx, "fish_spot_line",
                 {"spot_name": "湖", "periods": "晨", "rarity": "普通"})
    assert out.startswith("- ")


def test_intent_ref_line() -> None:
    """鱼讯参考行含三组关键词（逐字旧文案）。"""
    ctx = _ctx()
    out = tpl_of(ctx, "fish_intent_ref", {})
    assert "微动" in out and "拉扯" in out and "猛烈" in out
    assert "小鱼" in out and "中鱼" in out and "鱼王" in out


# ---------------------------------------------------------------------------
# 占位符缺失防御
# ---------------------------------------------------------------------------
def test_missing_placeholder_preserved() -> None:
    """占位符缺键 → 原样保留不崩（防御兜底）。"""
    ctx = _ctx()
    out = tpl_of(ctx, "fish_spot_line", {})
    assert "{spot_name}" in out  # 缺键原样保留


# ---------------------------------------------------------------------------
# 白名单（提示性：文档给内容包作者的占位符清单，非强制拦截——渲染器不校验）
# ---------------------------------------------------------------------------
def test_whitelist_documented() -> None:
    """白名单为文档提示（fish_spot_line 列 spot_name/periods/rarity），不强制拦截。"""
    assert set(PLACEHOLDER_WHITELIST["fish_spot_line"]) == {"spot_name", "periods", "rarity"}
    assert set(PLACEHOLDER_WHITELIST["fish_bite_triggered"]) == {"kind_cn", "golden_line"}
