"""双管线对拍测试（M4 实现审查批次1 P1-2 修复验证）。

依据：
  - 审查_M4实现_批次1_jspace.md P1-2（双管线平行实现口径漂移）：
      (a) require_at 下裸 / 触发——router 剥 / 放行绕过 @ 要求 → 修复为与 parsers 一致：
          require_at 时无 @ 一律忽略（含裸 /）。
      (b) require_at 下 @机器人 /攻击 2 组合——router 只剥 @ 残余 / 白名单失配 → 修复为
          「先剥 @ 再剥 /」统一顺序（对齐 parsers S0）。
      (c) 快捷展开到 GM 指令——parsers prefix_stripped 透传放行 GM → 修复为
          「spec.is_gm 且 '/' 前缀必须真正落在展开串上」（对齐 router _trigger_allowed）。
  - 2026-08-27 裁决① / m4_shared_contract §2.1 / 细化_3c §5.3（管线顺序 快捷→别名→白名单→忽略）
  - 补白：router 快捷展开串经 at_gate_passed 传递 @ 门（对齐 parsers 展开重入 require_at=False）。

覆盖：require_at×{裸/, @, @+/} × {普通/GM/快捷} 全矩阵 + GM 快捷子场景（(c) 修复钉死）
+ 非 require_at 基线。每个格子 3 断言：两管线各自命中期望 + 两管线互一致。

铁律：零 NoneBot import；纯函数；确定性。
"""
from __future__ import annotations

import pytest

from qbot_rpg.commands.parsers import (
    MODE_SESSION,
    parse_command,
)
from qbot_rpg.commands.router import (
    ROUTE_HIDDEN,
    ROUTE_IGNORED,
    ROUTE_SESSION,
    CommandSpec,
    Router,
    route_and_expand,
)

# ---------------------------------------------------------------------------
# 共享配置：parsers 与 router 双管线用同一语义源（攻击=普通 / 重载=GM / 快捷表）
# ---------------------------------------------------------------------------

WHITELIST = {"攻击", "防御", "对话", "重载"}
GM = {"重载"}
SHORTCUTS = {"1": "攻击3", "2": "重载", "3": "/重载"}  # 2→GM 无 /；3→GM 带 /
AT_TEXT = "@机器人"


def parse_pipeline(text: str, *, require_at: bool) -> tuple:
    """parsers 管线：parse_command 全量 S0-S8（含快捷展开）。"""
    p = parse_command(
        text,
        command_mode="global_shortcut",
        require_at=require_at,
        shortcuts=SHORTCUTS,
        whitelist=WHITELIST,
        prefix_required=GM | {"对话"},
        gm_commands=GM,
    )
    return norm_parsed(p)


def router_pipeline(text: str, *, require_at: bool) -> tuple:
    """router 管线：route_and_expand 全量（含一级快捷展开）。"""
    r = Router()
    for name, gm in (("攻击", False), ("防御", False), ("对话", False), ("重载", True)):
        r.register(CommandSpec(name, is_gm=gm))
    res = route_and_expand(text, {
        "registry": r,
        "shortcuts": SHORTCUTS,
        "aliases": None,
        "dialog_active": False,
        "battle_active": False,
        "command_mode": "global_shortcut",
        "require_at": require_at,
        "at_text": AT_TEXT,
    })
    return norm_routed(res)


def norm_parsed(p) -> tuple:
    """ParsedCommand → 可比较结果 (类别, 指令名)。"""
    if p.mode == MODE_SESSION or p.session_route:
        return ("session", None)
    if p.command is None:
        return ("ignored", None)
    return ("command", p.command)


def norm_routed(res) -> tuple:
    """RouteResult → 可比较结果 (类别, 指令名)。"""
    if res.kind == ROUTE_SESSION:
        return ("session", None)
    if res.kind == ROUTE_HIDDEN:  # keep_original=false 引导提示 = 不可执行
        return ("ignored", None)
    if res.kind == ROUTE_IGNORED or res.command is None:
        return ("ignored", None)
    return ("command", res.command)


# ---------------------------------------------------------------------------
# 对拍矩阵（审查建议：require_at×{裸/,@,@+/} × {普通/GM/快捷}）
# ---------------------------------------------------------------------------

REQUIRE_AT_CASES = [
    # (标签, 输入, 期望)
    # -- 普通（攻击）：require_at 下裸 / 需 @ → 忽略；@ 命中；@+/ 命中
    ("普通/裸/",       "/攻击 2",         ("ignored", None)),
    ("普通/@",         "@机器人 攻击 2",  ("command", "攻击")),
    ("普通/@+/",       "@机器人 /攻击 2", ("command", "攻击")),
    # -- GM（重载）：裸 / 无 @ → 忽略；@ 但无 / → 忽略（W07 仍需 /）；@+/ → 命中
    ("GM/裸/",         "/重载",           ("ignored", None)),
    ("GM/@",           "@机器人 重载",    ("ignored", None)),
    ("GM/@+/",         "@机器人 /重载",   ("command", "重载")),
    # -- 快捷（1→攻击3）：裸 / 无 @ → 忽略；@ 命中并展开；@+/ 命中并展开
    ("快捷/裸/",       "/1",              ("ignored", None)),
    ("快捷/@",         "@机器人 1",       ("command", "攻击")),
    ("快捷/@+/",       "@机器人 /1",      ("command", "攻击")),
    # -- GM 快捷（P1-2c 修复钉死）：
    #    2→重载（展开串无 /）：@ 与 @+/ 都命中快捷但展开后 GM 无真 / → 忽略
    ("GM快捷/@",       "@机器人 2",       ("ignored", None)),
    ("GM快捷/@+/",     "@机器人 /2",      ("ignored", None)),
    #    3→/重载（展开串自带 /）：前缀真正落在展开串上 → 命中
    ("GM快捷@+/带/",   "@机器人 /3",      ("command", "重载")),
]

NO_REQUIRE_AT_CASES = [
    # 非 require_at 基线：两种触发形态在全局模式下应一致
    ("普通/裸/",       "/攻击 2",         ("command", "攻击")),
    ("普通/裸发",      "攻击 2",          ("command", "攻击")),
    ("GM/裸/",         "/重载",           ("command", "重载")),
    ("GM/裸发",        "重载",            ("ignored", None)),
    ("快捷/裸/",       "/1",              ("command", "攻击")),
    ("快捷/裸发",      "1",               ("command", "攻击")),
]


@pytest.mark.parametrize("label,input_text,expected", REQUIRE_AT_CASES)
def test_require_at_parity(label, input_text, expected):
    parsed = parse_pipeline(input_text, require_at=True)
    routed = router_pipeline(input_text, require_at=True)
    assert parsed == expected, f"[parsers {label}] {input_text!r}"
    assert routed == expected, f"[router {label}] {input_text!r}"
    assert parsed == routed, f"[双管线不一致 {label}] {input_text!r}"


@pytest.mark.parametrize("label,input_text,expected", NO_REQUIRE_AT_CASES)
def test_no_require_at_parity(label, input_text, expected):
    parsed = parse_pipeline(input_text, require_at=False)
    routed = router_pipeline(input_text, require_at=False)
    assert parsed == expected, f"[parsers {label}] {input_text!r}"
    assert routed == expected, f"[router {label}] {input_text!r}"
    assert parsed == routed, f"[双管线不一致 {label}] {input_text!r}"


# ---------------------------------------------------------------------------
# 逐项回归钉死（修复可追溯，防回归）
# ---------------------------------------------------------------------------


def test_regression_a_bare_slash_requires_at():
    """P1-2a：require_at 下裸 / 触发不再绕过 @（router 曾放行，parsers 一直忽略）。"""
    assert parse_pipeline("/攻击 2", require_at=True) == ("ignored", None)
    assert router_pipeline("/攻击 2", require_at=True) == ("ignored", None)
    assert parse_pipeline("/重载", require_at=True) == ("ignored", None)
    assert router_pipeline("/重载", require_at=True) == ("ignored", None)


def test_regression_b_at_plus_slash_combination():
    """P1-2b：require_at 下 @机器人 /攻击 2 组合两管线都命中（router 曾失配忽略）。"""
    for text in ("@机器人 /攻击 2", "@机器人 /攻击2", "@机器人 /重载"):
        assert parse_pipeline(text, require_at=True) == router_pipeline(text, require_at=True), text


def test_regression_c_shortcut_to_gm_needs_slash_on_expansion():
    """P1-2c：GM 判定 = is_gm 且 '/' 真正落在展开串上（快捷授权不豁免 GM）。"""
    # 触发带 / 但展开串无 /（2→重载）：两管线都拦截
    for text in ("/2", "@机器人 2", "@机器人 /2"):
        assert parse_pipeline(text, require_at=True) == ("ignored", None), text
        assert router_pipeline(text, require_at=True) == ("ignored", None), text
    # 展开串自带 /（3→/重载）：命中（前缀在展开串上）
    assert parse_pipeline("@机器人 /3", require_at=True) == ("command", "重载")
    assert router_pipeline("@机器人 /3", require_at=True) == ("command", "重载")


def test_regression_c_prefix_only_shortcut_gm_blocked():
    """P1-2c（prefix_only 场景，审查原文）：/1 触发快捷展开到 GM 不再放行。"""
    r = Router()
    r.register(CommandSpec("重载", is_gm=True))
    r.register(CommandSpec("攻击"))
    ctx = {
        "registry": r,
        "shortcuts": {"1": "重载"},
        "dialog_active": False,
        "battle_active": False,
        "command_mode": "prefix_only",
        "require_at": False,
    }
    res = route_and_expand("/1", ctx)
    assert res.kind == ROUTE_IGNORED
    assert res.reason == "gm_requires_prefix"
    # parsers 同输入同语义：/1（prefix_only）→ 快捷 1→重载，展开串无 / → 忽略
    p = parse_command(
        "/1", command_mode="prefix_only", shortcuts={"1": "重载"},
        whitelist={"重载"}, prefix_required={"重载"}, gm_commands={"重载"},
    )
    assert p.command is None
    assert norm_parsed(p) == ("ignored", None)
