"""PVP 指令壳单测（tests/unit/test_pvp_commands.py · M11 批3 路3B）。

覆盖细化_4e CMD-05/06（/锁定玩家 /攻击玩家）+ CMD-R02~R05（参数解析 +
错误模板 4 类）+ 注册/白名单，对齐 docs/m11_启动包.md §2.3。
"""
from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from qbot_rpg.commands.pvp_commands import (
    ATTACK_PLAYER_CMD,
    LOCK_CMD,
    cmd_pvp_attack,
    cmd_pvp_lock,
    parse_pvp_attack_arg,
    parse_pvp_lock_arg,
    register_pvp_commands,
)
from qbot_rpg.commands.router import Router


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------
def _ctx(player: dict | None = None, **extra) -> dict:
    """指令壳 ctx：player/skills/registered/templates 全注入（引擎桩经 monkeypatch）。"""
    ctx = {
        "registered": True,
        "qid": "987654321",
        "player": player or {
            "qid": "987654321",
            "name": "阿伟",
            "level": 10,
            "job": "warrior",
            "hp": 100,
            "max_hp": 100,
        },
        "skills": {
            "s1": {"name": "斩击"},
            "s2": {"name": "火球"},
        },
    }
    ctx.update(extra)
    return ctx


class _P:
    """假 ParsedCommand（args 元组 + error 标记 + raw 片段）。"""

    def __init__(self, *args: str, error: str | None = None, raw: str = ""):
        self.args = tuple(args)
        self.error = error
        self.raw = raw or ("/锁定玩家 " + " ".join(args) if args else "/锁定玩家")


def _stub_engine(lock_result: dict, attack_result: dict):
    """引擎桩：pvp_lock / pvp_attack 返回注入结果（monkeypatch core.pvp 模块）。"""
    return SimpleNamespace(pvp_lock=lambda ctx, qq: lock_result,
                           pvp_attack=lambda ctx, skill_id: attack_result)


def _install_engine(monkeypatch, lock_result: dict, attack_result: dict):
    """把引擎桩装进 sys.modules（壳层 importlib 动态加载路径）。"""
    monkeypatch.setitem(sys.modules, "qbot_rpg.core.pvp",
                        _stub_engine(lock_result, attack_result))


# ---------------------------------------------------------------------------
# 参数解析（CMD-R02~R05）
# ---------------------------------------------------------------------------
def test_parse_lock_arg_qq_digits_9_11() -> None:
    """QQ=纯数字 9-11 位合法（群内 QQ 规则，CMD-R04）。"""
    assert parse_pvp_lock_arg(_P("123456789")) == "123456789"
    assert parse_pvp_lock_arg(_P("12345678901")) == "12345678901"


def test_parse_lock_arg_rejects_invalid_qq() -> None:
    """QQ 非 9-11 位纯数字 → None（缺参/格式错误模板，CMD-R04）。"""
    assert parse_pvp_lock_arg(_P()) is None            # 缺参
    assert parse_pvp_lock_arg(_P("123")) is None       # 过短
    assert parse_pvp_lock_arg(_P("123456789012")) is None  # 过长
    assert parse_pvp_lock_arg(_P("abc123456")) is None  # 含字母
    assert parse_pvp_lock_arg(_P("12345 6789")) is None  # 空格分隔


def test_parse_attack_arg_seq() -> None:
    """/攻击玩家 参数：技能序号（数字/名称/id）原样透传；缺参 → None。"""
    assert parse_pvp_attack_arg(_P("2")) == "2"
    assert parse_pvp_attack_arg(_P("斩击")) == "斩击"
    assert parse_pvp_attack_arg(_P()) is None


# ---------------------------------------------------------------------------
# /锁定玩家（CMD-05）
# ---------------------------------------------------------------------------
def test_lock_ok_renders_target_status(monkeypatch) -> None:
    """锁定成功 → 对方状态卡（等级/职业/血量/装备摘要）。"""
    _install_engine(monkeypatch,
                    lock_result={"ok": True, "target": {
                        "name": "小王", "level": 8, "job": "mage",
                        "hp": 60, "max_hp": 80,
                        "equipment": {"weapon": {"name": "法杖"}}}},
                    attack_result={})
    out = cmd_pvp_lock(_P("123456789"), _ctx())
    assert "✅ 已锁定玩家：小王" in out
    assert "【等级】8" in out
    assert "【职业】mage" in out
    assert "【血量】60/80" in out
    assert "【装备】weapon：法杖" in out


def test_lock_self_rejected() -> None:
    """锁定自己 → pvp_lock_self 拒绝（qq 与当前玩家 qid 相同）。"""
    out = cmd_pvp_lock(_P("987654321"), _ctx())
    assert "不能锁定自己" in out


def test_lock_self_via_player_qid() -> None:
    """锁定自己（qid 仅存于 player 内）→ pvp_lock_self 拒绝（_qid_of 兜底）。"""
    ctx = _ctx()
    ctx.pop("qid")
    out = cmd_pvp_lock(_P("987654321"), _ctx())
    assert "不能锁定自己" in out


def test_lock_missing_qq() -> None:
    """缺参 → pvp_err_missing（错误模板 4 类·缺参）。"""
    out = cmd_pvp_lock(_P(), _ctx())
    assert "请指定目标" in out


def test_lock_invalid_qq() -> None:
    """QQ 格式非法 → pvp_err_missing（CMD-R04 格式错误）。"""
    out = cmd_pvp_lock(_P("abc"), _ctx())
    assert "请指定目标" in out


def test_lock_unregistered_gate() -> None:
    """未注册 → 注册门槛拒绝（RUL-08）。"""
    out = cmd_pvp_lock(_P("123456789"), _ctx(registered=False))
    assert "请先 /注册" in out


def test_lock_engine_missing(monkeypatch) -> None:
    """引擎缺失（import 失败）→ 明确未接线提示（不静默）。"""
    import sys

    # importlib.import_module 对 sys.modules[name]=None 抛 ImportError
    monkeypatch.setitem(sys.modules, "qbot_rpg.core.pvp", None)
    out = cmd_pvp_lock(_P("123456789"), _ctx())
    assert "PVP 引擎未接线" in out


def test_lock_target_not_found(monkeypatch) -> None:
    """引擎返回无 ok → pvp_lock_not_found（对方未注册/不在线）。"""
    _install_engine(monkeypatch,
                    lock_result={"ok": False, "reason": "offline"},
                    attack_result={})
    out = cmd_pvp_lock(_P("123456789"), _ctx())
    assert "未找到玩家" in out


# ---------------------------------------------------------------------------
# /攻击玩家（CMD-06）
# ---------------------------------------------------------------------------
def test_attack_ok_renders_result(monkeypatch) -> None:
    """攻击成功 → 战斗结算消息（伤害行）。"""
    _install_engine(monkeypatch,
                    lock_result={},
                    attack_result={"ok": True, "name": "小王",
                                   "damage": 15, "hp": 45, "max_hp": 80,
                                   "result": "火球命中"})
    out = cmd_pvp_attack(_P("2"), _ctx())
    assert "✅ 对 小王 发起攻击" in out
    assert "小王 受到 15 点伤害，剩余 45/80" in out


def test_attack_missing_seq() -> None:
    """缺参 → pvp_err_missing。"""
    out = cmd_pvp_attack(_P(), _ctx())
    assert "请指定目标" in out


def test_attack_unknown_skill() -> None:
    """技能序号非法 → 值域拒绝（对齐 /攻击 battle_no_skill 口径，不走 TPL-12）。"""
    out = cmd_pvp_attack(_P("99"), _ctx())
    assert "请先 /锁定玩家" in out


def test_attack_unregistered_gate() -> None:
    """未注册 → 注册门槛拒绝。"""
    out = cmd_pvp_attack(_P("2"), _ctx(registered=False))
    assert "请先 /注册" in out


def test_attack_engine_missing(monkeypatch) -> None:
    """引擎缺失（import 失败）→ 明确未接线提示。"""
    import sys

    monkeypatch.setitem(sys.modules, "qbot_rpg.core.pvp", None)
    out = cmd_pvp_attack(_P("2"), _ctx())
    assert "PVP 引擎未接线" in out


def test_attack_no_locked_target(monkeypatch) -> None:
    """引擎返回无 ok（未锁定）→ pvp_attack_no_target。"""
    _install_engine(monkeypatch,
                    lock_result={},
                    attack_result={"ok": False, "reason": "no_target"})
    out = cmd_pvp_attack(_P("2"), _ctx())
    assert "请先 /锁定玩家" in out


# ---------------------------------------------------------------------------
# 解析错误模板 4 类（CMD-R05：缺参/超参/未知分隔符/保留字符）
# ---------------------------------------------------------------------------
def test_err_missing() -> None:
    """缺参 → pvp_err_missing。"""
    out = cmd_pvp_lock(_P(error="缺参"), _ctx())
    assert "请指定目标" in out


def test_err_too_many() -> None:
    """超参 → pvp_err_too_many。"""
    out = cmd_pvp_lock(_P("123456789", "99", error="超参"), _ctx())
    assert "参数过多" in out


def test_err_unknown_sep() -> None:
    """未知分隔符（列表/数量/键值）→ pvp_err_unknown_sep。"""
    out = cmd_pvp_lock(_P("123456789,99", error="未知分隔符"), _ctx())
    assert "不支持列表/数量/键值参数" in out


def test_err_reserved() -> None:
    """保留字符违规 → pvp_err_reserved。"""
    out = cmd_pvp_lock(_P("12345 6789", error="保留字符违规"), _ctx())
    assert "保留字符" in out


# ---------------------------------------------------------------------------
# 注册（register_pvp_commands + 白名单 + 前缀）
# ---------------------------------------------------------------------------
def test_register_registers_both_commands() -> None:
    """两个指令均注册（CommandSpec whitelisted=True，无 GM 标记）。"""
    router = Router()
    register_pvp_commands(router, make_context=lambda parsed: {})
    assert LOCK_CMD in router.names()
    assert ATTACK_PLAYER_CMD in router.names()
    spec = router.get(LOCK_CMD)
    assert spec is not None
    assert spec.whitelisted is True
    assert spec.is_gm is False


def test_register_make_context_required() -> None:
    """make_context 缺省 → handler 调用抛【待接线】RuntimeError（F-8）。"""
    router = Router()
    register_pvp_commands(router)
    spec = router.get(LOCK_CMD)
    assert spec is not None
    with pytest.raises(RuntimeError, match="【待接线】"):
        spec.handler(_P("123456789"))  # type: ignore[misc]


def test_whitelist_contains_pvp_commands() -> None:
    """白名单登记：锁定玩家/攻击玩家 ∈ DEFAULT_WHITELIST（S5 前缀匹配触发）。"""
    from qbot_rpg.commands.parsers import DEFAULT_PREFIX_REQUIRED, DEFAULT_WHITELIST
    assert LOCK_CMD in DEFAULT_WHITELIST
    assert ATTACK_PLAYER_CMD in DEFAULT_WHITELIST
    # 普通玩家指令不强制 / 前缀（可快捷；对齐 /攻击 口径）
    assert LOCK_CMD not in DEFAULT_PREFIX_REQUIRED
    assert ATTACK_PLAYER_CMD not in DEFAULT_PREFIX_REQUIRED


def test_parse_command_real_parsing() -> None:
    """经 parse_command 真实解析：/锁定玩家 123456789 命中白名单 → args 取到 QQ。"""
    from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
    p = parse_command("/锁定玩家 123456789", whitelist=DEFAULT_WHITELIST)
    assert p.command == LOCK_CMD
    assert p.args == ["123456789"]
    assert p.error is None
    p2 = parse_command("/攻击玩家 2", whitelist=DEFAULT_WHITELIST)
    assert p2.command == ATTACK_PLAYER_CMD
    assert p2.args == ["2"]


# ---------------------------------------------------------------------------
# 模板分区（pvp_tpl：白名单完整性 + 默认文案可覆盖）
# ---------------------------------------------------------------------------
def test_pvp_tpl_whitelist_coverage() -> None:
    """白名单完整性：pvp 分区模板占位符 ⊆ 白名单，登记 key 与模板表一一对应。"""
    import re

    from qbot_rpg.core.templates.pvp_tpl import (
        DEFAULT_TEMPLATES as PT,
        PLACEHOLDER_WHITELIST as PW,
    )
    assert set(PT) == set(PW)
    for key, tpl in PT.items():
        ph = set(re.findall(r"\{([a-zA-Z0-9_]+)\}", str(tpl)))
        assert ph <= PW[key], f"{key}: {ph - PW[key]} 不在白名单"


def test_pvp_tpl_registered_in_global_registry() -> None:
    """pvp 分区登记进 templates 全局注册表（两清单含 pvp_* key）。"""
    from qbot_rpg.core.templates import DEFAULT_TEMPLATES, PLACEHOLDER_WHITELIST
    assert "pvp_lock_ok" in DEFAULT_TEMPLATES
    assert "pvp_err_missing" in PLACEHOLDER_WHITELIST


def test_pvp_tpl_override_via_ctx(monkeypatch) -> None:
    """内容包覆盖：ctx[\"templates\"] 覆盖 pvp 分区默认 → 渲染处 tpl_of 生效。"""
    from qbot_rpg.core.templates import resolve_templates
    _install_engine(monkeypatch,
                    lock_result={"ok": True, "target": {
                        "name": "小王", "level": 8, "job": "mage",
                        "hp": 60, "max_hp": 80, "equipment": {}}},
                    attack_result={})
    ctx = _ctx()
    ctx["templates"] = resolve_templates({"pvp_lock_ok": "【PVP】已锁定 {name}"})
    out = cmd_pvp_lock(_P("123456789"), ctx)
    assert "【PVP】已锁定" in out
