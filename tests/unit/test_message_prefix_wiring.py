"""message_prefix 前缀消费接线单测（M5-01 公共接线 · qbot_rpg/commands/prefix_wiring.py）。

依据：docs/m5_shared_contract.md §一（IF02 settings 读取 / IF01b truncated 消费 / 铁律 1/8）
     + docs/m5_batch_plan.md M5-01 验收①~⑥ + 细化_3d §1.5/§3.3（TC-13/TC-23/TC-24/TC-25/TC-26）。

覆盖：① show_on_system=false 系统消息无前缀、true 有 ② per_channel=group/private 渠道限定
      ③ enabled=false 完全无前缀 ④ 玩家回复首行带前缀、多行仅首行 ⑤ 前缀超长截断+黄提示、正文照常
      （TC-13）⑥ 前缀不影响解析（渲染层产物不进解析器，TC-26）。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands.prefix_wiring import (
    CHANNEL_GROUP,
    CHANNEL_PRIVATE,
    DEFAULT_MESSAGE_PREFIX_SETTINGS,
    PER_CHANNEL_ALL,
    PER_CHANNEL_GROUP,
    PER_CHANNEL_PRIVATE,
    PREFIX_TRUNCATED_HINT,
    PrefixWiringResult,
    apply_message_prefix,
    read_message_prefix_settings,
)
from qbot_rpg.commands.router import (
    CommandSpec,
    ROUTE_COMMAND,
    ROUTE_IGNORED,
    Router,
    route_message,
)

# 玩家上下文缺省（阿伟 35 级）
LV, NAME, TITLE = 35, "阿伟", "斩龙者"


def _router_ctx() -> dict:
    """通用路由上下文 dict（对齐 test_router.mk_ctx 口径）。"""
    r = Router()
    r.register(CommandSpec("攻击", handler=lambda *a: "atk"))
    return {
        "registry": r,
        "shortcuts": {},
        "aliases": None,
        "dialog_active": False,
        "battle_active": False,
        "command_mode": "global_shortcut",
        "require_at": False,
    }


# ---------------------------------------------------------------------------
# settings 读取（IF02：7 字段缺省合并 / 两种传法 / 非法兜底）
# ---------------------------------------------------------------------------

def test_read_settings_defaults_all_seven_fields() -> None:
    """缺省 = 7 字段框架默认值（shared_contract §1.1 / 【前缀】§三）。"""
    assert read_message_prefix_settings(None) == {
        "enabled": True,
        "format": "Lv[等级].[玩家名] -[称号]-",
        "show_on_system": False,
        "per_channel": "all",
        "hide_when_empty": False,
        "empty_title_text": "-",
        "prefix_max_len": 40,
    }
    assert read_message_prefix_settings({}) == DEFAULT_MESSAGE_PREFIX_SETTINGS


def test_read_settings_segment_shape() -> None:
    """直接传 message_prefix 段本体 → 只覆盖提供的字段，其余保持默认。"""
    cfg = read_message_prefix_settings({"enabled": False, "per_channel": "group", "prefix_max_len": 0})
    assert cfg["enabled"] is False
    assert cfg["per_channel"] == "group"
    assert cfg["prefix_max_len"] == 0
    assert cfg["format"] == "Lv[等级].[玩家名] -[称号]-"  # 未覆盖字段保持默认


def test_read_settings_nested_full_settings_shape() -> None:
    """传完整 settings.json 映射（含 message_prefix 键）→ 解包该段。"""
    cfg = read_message_prefix_settings({"message_prefix": {"show_on_system": True, "format": "[职业] Lv[等级].[玩家名]"}})
    assert cfg["show_on_system"] is True
    assert cfg["format"] == "[职业] Lv[等级].[玩家名]"
    assert cfg["enabled"] is True and cfg["prefix_max_len"] == 40  # 未覆盖字段保持默认


def test_read_settings_invalid_per_channel_falls_back_all() -> None:
    """per_channel 非法枚举 → 按 all 兜底（只建议不限制，不拦截）。"""
    assert read_message_prefix_settings({"per_channel": "频道"})["per_channel"] == "all"


def test_read_settings_rejects_non_mapping() -> None:
    with pytest.raises(TypeError):
        read_message_prefix_settings(42)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 默认渲染 TPL-01（真实签名 render_prefix_result 委托；[群名]/[职业] 经 extra）
# ---------------------------------------------------------------------------

def test_default_render_tpl01() -> None:
    """默认配置：`Lv[等级].[玩家名] -[称号]-` → 前缀挂首行。"""
    res = apply_message_prefix("✅ 你施放火球术", level=LV, name=NAME, title=TITLE)
    assert res.text == "Lv35.阿伟 -斩龙者-\n✅ 你施放火球术"
    assert not res.truncated and not res.hint


def test_extra_placeholders_group_and_job() -> None:
    """TPL-06 群名片版 + 职业：extra 注入 [群名]/[职业]（IF01b extra 参数）。"""
    cfg = {"format": "【[群名]】[职业] Lv[等级].[玩家名]"}
    res = apply_message_prefix(
        "正文", level=LV, name=NAME, title=None, channel=CHANNEL_GROUP,
        settings=cfg, extra={"群名": "冒险者公会", "职业": "战士"},
    )
    assert res.text == "【冒险者公会】战士 Lv35.阿伟\n正文"


# ---------------------------------------------------------------------------
# ① show_on_system：系统公告/群广播默认不加，true 加（TC-24）
# ---------------------------------------------------------------------------

def test_system_message_no_prefix_by_default() -> None:
    """show_on_system 默认 false：系统公告/群广播不加前缀。"""
    res = apply_message_prefix("系统公告：服务器维护", level=LV, name=NAME, title=None, is_system=True)
    assert res.text == "系统公告：服务器维护"
    assert not res.truncated and not res.hint


def test_system_message_prefix_when_show_on_system() -> None:
    """show_on_system=true：系统公告同样加前缀。"""
    cfg = {"show_on_system": True}
    res = apply_message_prefix(
        "系统公告：服务器维护", level=LV, name=NAME, title=None, is_system=True, settings=cfg,
    )
    assert res.text.startswith("Lv35.阿伟")
    assert "\n系统公告：服务器维护" in res.text


# ---------------------------------------------------------------------------
# ② per_channel：渠道限定（TC-25）
# ---------------------------------------------------------------------------

def test_per_channel_group_only_group() -> None:
    """per_channel=group：仅群聊生效，私聊不加。"""
    cfg = {"per_channel": PER_CHANNEL_GROUP}
    res_group = apply_message_prefix("正文", level=LV, name=NAME, channel=CHANNEL_GROUP, settings=cfg)
    assert res_group.text.startswith("Lv35.阿伟")
    res_private = apply_message_prefix("正文", level=LV, name=NAME, channel=CHANNEL_PRIVATE, settings=cfg)
    assert res_private.text == "正文"


def test_per_channel_private_only_private() -> None:
    """per_channel=private：仅私聊生效，群聊不加。"""
    cfg = {"per_channel": PER_CHANNEL_PRIVATE}
    res_private = apply_message_prefix("正文", level=LV, name=NAME, channel=CHANNEL_PRIVATE, settings=cfg)
    assert res_private.text.startswith("Lv35.阿伟")
    res_group = apply_message_prefix("正文", level=LV, name=NAME, channel=CHANNEL_GROUP, settings=cfg)
    assert res_group.text == "正文"


def test_per_channel_all_both() -> None:
    """per_channel=all（默认）：群聊+私聊都生效。"""
    cfg = {"per_channel": PER_CHANNEL_ALL}
    for ch in (CHANNEL_GROUP, CHANNEL_PRIVATE):
        res = apply_message_prefix("正文", level=LV, name=NAME, channel=ch, settings=cfg)
        assert res.text.startswith("Lv35.阿伟")


# ---------------------------------------------------------------------------
# ③ enabled=false：完全无前缀（【前缀】L42）
# ---------------------------------------------------------------------------

def test_disabled_no_prefix_whatsoever() -> None:
    """enabled=false：完全无前缀，多行正文原样返回。"""
    body = "正文多行\n第二行"
    cfg = {"enabled": False}
    res = apply_message_prefix(body, level=LV, name=NAME, title=TITLE, settings=cfg)
    assert res.text == body
    assert not res.truncated and not res.hint


# ---------------------------------------------------------------------------
# ④ 玩家回复首行带前缀、多行仅首行（TC-23 / 铁律 1）
# ---------------------------------------------------------------------------

def test_prefix_only_first_line_of_multiline() -> None:
    """战斗轮内多行回复：前缀只出现在消息首行，后续每行无前缀（TC-23）。"""
    body = (
        "✅ 你施放火球术，造成 18 伤害（史莱姆 7/25）\n"
        "❌ 史莱姆反击，你受到 4 伤害（HP 21/30）\n"
        "你 21/30 | 史莱姆 7/25 → /攻击 /防御"
    )
    res = apply_message_prefix(body, level=LV, name=NAME, title=TITLE)
    lines = res.text.split("\n")
    assert lines[0] == "Lv35.阿伟 -斩龙者-"
    assert lines[1] == "✅ 你施放火球术，造成 18 伤害（史莱姆 7/25）"
    assert lines[2] == "❌ 史莱姆反击，你受到 4 伤害（HP 21/30）"
    assert not any("Lv35" in ln for ln in lines[1:])  # 仅首行带前缀


def test_empty_reply_stays_empty() -> None:
    res = apply_message_prefix("", level=LV, name=NAME, title=None)
    assert res.text == ""


# ---------------------------------------------------------------------------
# ⑤ 前缀超长截断 + 黄提示，正文照常（TC-13）
# ---------------------------------------------------------------------------

def test_truncation_hint_and_body_untouched() -> None:
    """prefix_max_len 极小 → 截断 + 黄提示「前缀过长已截断」，正文照常输出。"""
    cfg = {"prefix_max_len": 10}
    res = apply_message_prefix("正文照常输出", level=LV, name=NAME, title=TITLE, settings=cfg)
    first = res.text.split("\n", 1)[0]
    assert len(first) <= 10  # 截断至 prefix_max_len
    assert res.truncated is True
    assert res.hint == PREFIX_TRUNCATED_HINT == "前缀过长已截断"
    assert "\n正文照常输出" in res.text  # 正文不受影响（TC-13）
    assert res.has_hint is True


def test_default_max_len_truncates_long_title() -> None:
    """默认 prefix_max_len=40：超长称号触发截断 + 黄提示。"""
    res = apply_message_prefix("正文", level=LV, name=NAME, title="超长称号" * 30)
    first = res.text.split("\n", 1)[0]
    assert len(first) == 40
    assert res.truncated is True and res.hint == PREFIX_TRUNCATED_HINT
    assert "\n正文" in res.text


def test_prefix_max_len_zero_unlimited() -> None:
    """prefix_max_len=0 → 不限，不截断不黄提示。"""
    cfg = {"prefix_max_len": 0}
    res = apply_message_prefix("正文", level=LV, name=NAME, title="超长称号" * 30, settings=cfg)
    assert res.truncated is False and not res.hint
    assert "超长称号" in res.text.split("\n", 1)[0]


# ---------------------------------------------------------------------------
# ⑥ 前缀不影响指令解析（TC-26 / 铁律 1：渲染层产物不进解析器）
# ---------------------------------------------------------------------------

def test_prefix_does_not_affect_parsing() -> None:
    """玩家发前缀样式文本作指令 → 解析用原文，前缀样式不影响解析。"""
    ctx = _router_ctx()
    # ① 前缀样式文本（渲染层产物）作为输入 → 非指令，忽略
    routed = route_message("Lv35.阿伟 -斩龙者-", ctx)
    assert routed.kind == ROUTE_IGNORED
    # ② 原指令 /攻击 2 照常命中，command 名无前缀污染
    cmd = route_message("/攻击 2", ctx)
    assert cmd.kind == ROUTE_COMMAND
    assert cmd.command == "攻击"
    # ③ 前缀是发送前才挂的首行：装配输出首行=前缀，正文/指令串原文保留
    assembled = apply_message_prefix("攻击 2", level=LV, name=NAME, title=None)
    assert assembled.text == "Lv35.阿伟 - -\n攻击 2"  # 无称号默认空称号文本
    assert assembled.text.endswith("攻击 2")
