"""路由器 router.py 单测（M4 批次1·路B3 · qbot_rpg/commands/router.py）。

依据：m4_shared_contract.md §2.1（路由管线 快捷表→别名→白名单→忽略；会话路由；裁决①战斗中
裸数字=快捷表）+ 细化_3c_指令解析契约 §5（R1-R5 / 5.3 优先级总表）+ §4（快捷冲突 C01-C05 /
E03 上限 / 别名 A01-A08）+ 细化_2b2（结束词三同义 / 会话激活区间）+ 2026-08-27 裁决①。

覆盖：指令注册表（名称/解析函数/白名单标记/GM 权限标记/冲突）· 会话路由（R1-R3 + 裁决①不送
战斗会话）· 快捷表（精确匹配/一级展开/深度防环/前缀形态）· 指令别名（A03-A05 keep_original）·
白名单/忽略（W06/W07 非指令不误触、GM 强制前缀、command_mode 三模式）· GM 禁绑（C01/C02/C03/E03）。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands.router import (
    PERM_GM,
    MODE_ALIAS,
    MODE_NORMAL,
    MODE_SHORTCUT,
    MODE_SESSION_DIGIT,
    ROUTE_ALIAS,
    ROUTE_COMMAND,
    ROUTE_HIDDEN,
    ROUTE_IGNORED,
    ROUTE_SESSION,
    ROUTE_SHORTCUT,
    SESSION_EXIT_WORDS,
    SESSION_SUBWORD_CONTINUE,
    SESSION_SUBWORD_DIGIT,
    SESSION_SUBWORD_EXIT,
    SESSION_SUBWORD_SELECT,
    AliasEntry,
    AliasTable,
    CommandSpec,
    Router,
    check_shortcut_binding,
    check_shortcut_limit,
    is_gm_command,
    is_session_subword,
    normalize_aliases,
    register_command,
    resolve_command_word,
    route_and_expand,
    route_message,
)

# ---------------------------------------------------------------------------
# 夹具：通用注册表 + 路由上下文
# ---------------------------------------------------------------------------

# 固定子词表（S6 裁决：动态注册表 = 框架指令 + 内容包 + 固定子词）
FIXED_SUBWORDS = ["追加", "预览", "自动", "查看", "确认", "放弃", "续"]


def make_router() -> Router:
    """通用 Router：普通指令 + GM 指令 + 白名单外指令。"""
    r = Router()
    r.register(CommandSpec("攻击", handler=lambda *a: "atk"))
    r.register(CommandSpec("使用", handler=lambda *a: "use"))
    r.register(CommandSpec("背包", handler=lambda *a: "bag"))
    r.register(CommandSpec("防御", handler=lambda *a: "def"))
    r.register(CommandSpec("对话", handler=lambda *a: "dialog"))
    r.register(CommandSpec("锻造", handler=lambda *a: "forge"))
    r.register(CommandSpec("炼金", handler=lambda *a: "alchemy"))
    r.register(CommandSpec("重载", permission=PERM_GM, is_gm=True, handler=lambda *a: "gm_reload"))
    r.register(CommandSpec("设置", permission=PERM_GM, is_gm=True, handler=lambda *a: "gm_set"))
    r.register(CommandSpec("内部", whitelisted=False, handler=lambda *a: "internal"))
    return r


def mk_ctx(router: Router, **kw) -> dict:
    """默认路由上下文 dict（registry=router；其余可覆盖）。"""
    ctx = {
        "registry": router,
        "shortcuts": {},
        "aliases": None,
        "dialog_active": False,
        "battle_active": False,
        "command_mode": "global_shortcut",
        "require_at": False,
    }
    ctx.update(kw)
    return ctx


# ===========================================================================
# 一、指令注册表（CommandSpec：名称/解析函数/白名单标记/GM 权限标记）
# ===========================================================================

def test_command_spec_fields():
    spec = CommandSpec("攻击", handler=lambda *a: 1, whitelisted=True, is_gm=False)
    assert spec.name == "攻击"
    assert spec.whitelisted is True
    assert spec.is_gm is False
    assert spec.handler is not None
    assert spec.permission == "user"
    spec_gm = CommandSpec("重载", permission=PERM_GM, is_gm=True)
    assert spec_gm.is_gm is True
    assert spec_gm.permission == PERM_GM


def test_command_spec_empty_name_rejected():
    with pytest.raises(ValueError):
        CommandSpec("")


def test_command_spec_matches_name_alias_prefix():
    spec = CommandSpec("锻造", aliases=["炼器"])
    assert spec.matches("锻造")
    assert spec.matches("炼器")
    assert spec.matches("/锻造")
    assert not spec.matches("使用")


def test_router_register_duplicate_conflict():
    r = Router()
    r.register(CommandSpec("攻击"))
    with pytest.raises(ValueError):
        r.register(CommandSpec("攻击"))
    # replace=True 允许覆盖（热重载）
    r.register(CommandSpec("攻击", is_gm=True), replace=True)
    assert r.get("攻击").is_gm is True


def test_router_whitelist_and_gm_sets():
    r = make_router()
    # 白名单：whitelisted=True 的才参与 S5 匹配（内部 excluded）
    assert "内部" not in r.whitelist_names()
    assert "攻击" in r.whitelist_names()
    # GM 指令名集合
    assert set(r.gm_commands()) == {"重载", "设置"}
    assert r.has("攻击") and not r.has("不存在")
    assert "重载" in r.names()


def test_router_unregister():
    r = Router()
    r.register(CommandSpec("攻击"))
    assert r.unregister("攻击") is True
    assert r.unregister("攻击") is False
    assert not r.has("攻击")


def test_router_dispatch_uses_self_registry():
    r = make_router()
    res = r.dispatch("攻击 2")
    assert res.kind == ROUTE_COMMAND
    assert res.command == "攻击"
    assert res.args_text == "2"


# ===========================================================================
# 二、会话路由（2b2 R1-R5 + 3c §5.1 + 裁决①）
# ===========================================================================

def test_tc36_dialog_pure_digit_to_session():
    r = make_router()
    ctx = mk_ctx(r, dialog_active=True)
    res = route_message("2", ctx)
    assert res.kind == ROUTE_SESSION
    assert res.mode == MODE_SESSION_DIGIT
    assert res.session_route is True
    assert res.subword == (SESSION_SUBWORD_DIGIT, 2)


def test_dialog_continue_to_session():
    res = route_message("继续", mk_ctx(make_router(), dialog_active=True))
    assert res.kind == ROUTE_SESSION
    assert res.subword == (SESSION_SUBWORD_CONTINUE, None)


def test_dialog_exit_three_synonyms():
    """结束词三同义（2b2 L62）：退出/离开/再见 行为一致。"""
    r = make_router()
    for word in SESSION_EXIT_WORDS:
        assert word in ("退出", "离开", "再见")
        res = route_message(word, mk_ctx(r, dialog_active=True))
        assert res.kind == ROUTE_SESSION
        assert res.subword == (SESSION_SUBWORD_EXIT, None)


def test_dialog_select_n_both_forms():
    r = make_router()
    for inp in ("选择 2", "选择2"):
        res = route_message(inp, mk_ctx(r, dialog_active=True))
        assert res.kind == ROUTE_SESSION
        assert res.subword == (SESSION_SUBWORD_SELECT, 2)


def test_tc37_dialog_command_word_parses_normally():
    """R2：带指令词照常解析（会话中也能『使用1』吃药）。"""
    r = make_router()
    ctx = mk_ctx(r, dialog_active=True)
    res = route_message("使用1", ctx)
    assert res.kind == ROUTE_COMMAND
    assert res.command == "使用"
    assert res.args_text == "1"
    assert not res.session_route


def test_tc38_session_wins_over_shortcut_r3():
    """R3：已绑『1=攻击』，对话激活中发 1 → 选选项不触发攻击。"""
    r = make_router()
    ctx = mk_ctx(r, dialog_active=True, shortcuts={"1": "攻击"})
    res = route_message("1", ctx)
    assert res.kind == ROUTE_SESSION
    assert res.subword == (SESSION_SUBWORD_DIGIT, 1)


def test_ruling1_battle_bare_digit_goes_shortcut_not_session():
    """2026-08-27 裁决①：战斗中裸数字 = 快捷表（无会话上下文），不送会话。"""
    r = make_router()
    ctx = mk_ctx(r, battle_active=True, shortcuts={"1": "攻击"})
    res = route_message("1", ctx)
    assert res.kind == ROUTE_SHORTCUT
    assert res.shortcut_command == "攻击"


def test_battle_bare_digit_unbound_ignored():
    """战斗中裸数字未绑定 → 走快捷表未命中 → 白名单不命中 → 忽略（裁决①语义）。"""
    res = route_message("7", mk_ctx(make_router(), battle_active=True))
    assert res.kind == ROUTE_IGNORED


def test_battle_command_word_parses_normally():
    res = route_message("攻击2", mk_ctx(make_router(), battle_active=True))
    assert res.kind == ROUTE_COMMAND
    assert res.command == "攻击"


def test_tc41_no_session_shortcut_effective_r4():
    """R4：无会话上下文发 1（已绑 1=攻击）→ 快捷生效。"""
    r = make_router()
    ctx = mk_ctx(r, shortcuts={"1": "攻击"})
    assert route_message("1", ctx).kind == ROUTE_SHORTCUT
    # 未绑定 → 忽略
    assert route_message("1", mk_ctx(r)).kind == ROUTE_IGNORED
    # 随机文本不误触
    assert route_message("xyz", mk_ctx(r)).kind == ROUTE_IGNORED


def test_is_session_subword_unit():
    assert is_session_subword("1") == (SESSION_SUBWORD_DIGIT, 1)
    assert is_session_subword("10") == (SESSION_SUBWORD_DIGIT, 10)
    assert is_session_subword("继续") == (SESSION_SUBWORD_CONTINUE, None)
    assert is_session_subword("退出") == (SESSION_SUBWORD_EXIT, None)
    assert is_session_subword("选择 3") == (SESSION_SUBWORD_SELECT, 3)
    assert is_session_subword("选择3") == (SESSION_SUBWORD_SELECT, 3)
    assert is_session_subword("选择") is None          # 无 N 不算子词
    assert is_session_subword("攻击2") is None          # 带指令词非子词
    assert is_session_subword("") is None
    assert is_session_subword("   ") is None


# ===========================================================================
# 三、快捷表（L149① 精确匹配 / S7 一级展开 / E05 前缀形态）
# ===========================================================================

def test_tc24_shortcut_exact_full_message_match():
    r = make_router()
    ctx = mk_ctx(r, shortcuts={"火球": "攻击3", "1": "攻击"})
    res = route_message("火球", ctx)
    assert res.kind == ROUTE_SHORTCUT
    assert res.mode == MODE_SHORTCUT
    assert res.shortcut_command == "攻击3"
    # 非完整消息不命中（L153：攻击2 不被快捷影响）
    assert route_message("攻击2", ctx).kind == ROUTE_COMMAND


def test_tc25_shortcut_expands_with_args():
    r = make_router()
    ctx = mk_ctx(r, shortcuts={"奶": "使用 治疗药水*2"})
    res = route_and_expand("奶", ctx)
    assert res.kind == ROUTE_COMMAND
    assert res.command == "使用"
    assert res.args_text == "治疗药水*2"
    assert res.mode == MODE_SHORTCUT          # 触发来源保留（P03）
    assert res.expand_count == 1              # P04 展开深度=1
    assert res.shortcut_name == "奶"
    assert res.shortcut_command == "使用 治疗药水*2"


def test_shortcut_expansion_no_recursion_depth_1():
    """S7 裁决：快捷展开深度=1，命中快捷后不回查快捷表（防 A→B→A 无限循环）。"""
    r = make_router()
    ctx = mk_ctx(r, shortcuts={"a": "b", "b": "攻击"})
    res = route_and_expand("a", ctx)
    # b 也是快捷名，但展开后 allow_shortcut=False 不再回查 → 走白名单未命中 → 忽略
    assert res.kind == ROUTE_IGNORED
    assert res.expand_count == 1


def test_shortcut_prefixed_form_e05():
    """E05：prefix_only 模式发 /1 = 快捷触发；裸 1 不触发（前缀联动）。"""
    r = make_router()
    ctx = mk_ctx(r, command_mode="prefix_only", shortcuts={"1": "攻击"})
    # 裸 1 → 前缀必需未带 → 忽略
    assert route_message("1", ctx).kind == ROUTE_IGNORED
    # /1 → 剥离 / 后精确匹配快捷名
    res = route_message("/1", ctx)
    assert res.kind == ROUTE_SHORTCUT
    assert res.prefix_stripped is True
    assert res.shortcut_command == "攻击"
    # E01：/ 触发后展开串不再受前缀门控 → 完整管线执行
    full = route_and_expand("/1", ctx)
    assert full.kind == ROUTE_COMMAND
    assert full.command == "攻击"
    assert full.mode == MODE_SHORTCUT


def test_prefix_only_bare_alias_gated():
    """E05 联动：prefix_only 下裸别名不触发（需 /）。"""
    r = make_router()
    ctx = mk_ctx(r, command_mode="prefix_only", aliases={"炼金": {"alias": "炼丹", "keep_original": False}})
    assert route_message("炼丹", ctx).kind == ROUTE_IGNORED
    assert route_message("/炼丹", ctx).kind == ROUTE_ALIAS


def test_shortcut_gm_target_exposes_is_gm_for_e02():
    """E02：GM 指令即使被意外绑定也不执行 → 路由暴露 is_gm 供执行层二次检查。"""
    r = make_router()
    ctx = mk_ctx(r, shortcuts={"x": "/重载"})
    res = route_and_expand("x", ctx)
    assert res.kind == ROUTE_COMMAND
    assert res.command == "重载"
    assert res.is_gm is True
    assert res.spec.is_gm is True


# ===========================================================================
# 四、指令别名（A03-A05：执行原指令 / 显示层替换 / keep_original）
# ===========================================================================

def test_tc33_alias_executes_original():
    """A03：发『炼丹』=炼金；带参别名『炼丹 火灵丹*3』=炼金 火灵丹*3。"""
    r = make_router()
    aliases = {"炼金": {"alias": "炼丹", "keep_original": False}}
    ctx = mk_ctx(r, aliases=aliases)
    res = route_message("炼丹", ctx)
    assert res.kind == ROUTE_ALIAS
    assert res.mode == MODE_ALIAS
    assert res.command == "炼金"
    assert res.display_name == "炼丹"
    assert res.args_text == ""
    res2 = route_message("炼丹 火灵丹*3", ctx)
    assert res2.command == "炼金"
    assert res2.args_text == "火灵丹*3"


def test_tc33_keep_original_false_hides_original():
    """A04：keep_original=false 发原指令 → hidden_original（提示『试试炼丹？』）。"""
    r = make_router()
    aliases = {"炼金": {"alias": "炼丹", "keep_original": False}}
    res = route_message("炼金", mk_ctx(r, aliases=aliases))
    assert res.kind == ROUTE_HIDDEN
    assert res.command == "炼金"
    assert res.display_name == "炼丹"


def test_tc35_keep_original_true_original_still_works_display_replaced():
    """A05：keep_original=true（默认）原指令可用，显示层全用别名。"""
    r = make_router()
    aliases = {"锻造": "炼器"}  # 默认 keep_original=True
    ctx = mk_ctx(r, aliases=aliases)
    # 发别名
    res_alias = route_message("炼器", ctx)
    assert res_alias.kind == ROUTE_ALIAS
    assert res_alias.command == "锻造"
    assert res_alias.display_name == "炼器"
    # 发原指令 → 正常命中，显示层仍替换为别名
    res_cmd = route_message("锻造 炎剑Ⅱ", ctx)
    assert res_cmd.kind == ROUTE_COMMAND
    assert res_cmd.command == "锻造"
    assert res_cmd.display_name == "炼器"
    assert res_cmd.args_text == "炎剑Ⅱ"


def test_alias_compact_form():
    """【工程补白】别名紧凑形态（炼丹3）按前缀匹配。"""
    r = make_router()
    ctx = mk_ctx(r, aliases={"炼金": {"alias": "炼丹", "keep_original": False}})
    res = route_message("炼丹3", ctx)
    assert res.kind == ROUTE_ALIAS
    assert res.command == "炼金"
    assert res.args_text == "3"
    assert res.compact is True


def test_normalize_aliases_config_forms():
    """A02 配置形态归一：短字符串 / dict(alias) / dict(command)。"""
    table = normalize_aliases({"锻造": "炼器", "炼金": {"alias": "炼丹", "keep_original": False}})
    assert table.alias_for("炼器") == AliasEntry("锻造", "炼器", keep_original=True)
    assert table.alias_for("炼丹").keep_original is False
    assert table.for_command("锻造").alias == "炼器"
    assert table.display_name("锻造") == "炼器"
    assert table.display_name("攻击") == "攻击"   # 无别名 → 原指令名

    table2 = normalize_aliases({"炼丹": {"command": "炼金", "keep_original": False}})
    assert table2.alias_for("炼丹").command == "炼金"

    assert not normalize_aliases(None)
    assert not normalize_aliases({})


def test_normalize_aliases_invalid_config_raises():
    with pytest.raises(ValueError):
        normalize_aliases({"炼金": {"foo": 1}})
    with pytest.raises(TypeError):
        normalize_aliases("炼金")


def test_alias_table_alias_names_and_commands():
    table = AliasTable.from_config({"锻造": "炼器"})
    assert table.alias_names() == {"炼器"}
    assert table.commands() == {"锻造"}


# ===========================================================================
# 五、白名单 / 忽略（S5 ③ ④ + W06/W07 + command_mode 三模式）
# ===========================================================================

def test_whitelist_space_and_compact_dual():
    """S6 双认：『攻击 2』与『攻击2』解析结果等价。"""
    r = make_router()
    ctx = mk_ctx(r)
    a = route_message("攻击 2", ctx)
    b = route_message("攻击2", ctx)
    assert a.kind == ROUTE_COMMAND and a.command == "攻击" and a.args_text == "2"
    assert b.kind == ROUTE_COMMAND and b.command == "攻击" and b.args_text == "2"
    assert b.compact is True
    assert a.compact is False


def test_ignore_non_command_message_w06():
    """W06：非指令消息不响应（随机群聊文本不误触）。"""
    res = route_message("今天天气真好", mk_ctx(make_router()))
    assert res.kind == ROUTE_IGNORED
    assert res.reason == "no_match"


def test_tc22_gm_command_requires_prefix_w07():
    """W07/TC-22：GM 指令强制 / 前缀，任意模式裸发重载 不命中。"""
    r = make_router()
    ctx = mk_ctx(r)
    # 带 / → 命中
    assert route_message("/重载", ctx).kind == ROUTE_COMMAND
    assert route_message("/重载", ctx).command == "重载"
    # 裸发 → 忽略（含全局免前缀模式）
    res = route_message("重载", ctx)
    assert res.kind == ROUTE_IGNORED
    assert res.reason == "gm_requires_prefix"


def test_command_mode_prefix_only():
    """TC-20：prefix_only 全部需 /（战斗内也需 /）。"""
    r = make_router()
    ctx = mk_ctx(r, command_mode="prefix_only")
    assert route_message("攻击2", ctx).kind == ROUTE_IGNORED
    assert route_message("攻击2", ctx).reason == "prefix_required"
    assert route_message("/攻击 2", ctx).kind == ROUTE_COMMAND
    assert route_message("攻击2", mk_ctx(r, command_mode="prefix_only", battle_active=True)).kind == ROUTE_IGNORED


def test_command_mode_combat_shortcut():
    """TC-20：combat_shortcut 战斗内免前缀、战斗外需 /。"""
    r = make_router()
    assert route_message("攻击2", mk_ctx(r, command_mode="combat_shortcut", battle_active=True)).kind == ROUTE_COMMAND
    assert route_message("攻击2", mk_ctx(r, command_mode="combat_shortcut")).kind == ROUTE_IGNORED
    assert route_message("/攻击 2", mk_ctx(r, command_mode="combat_shortcut")).kind == ROUTE_COMMAND


def test_command_mode_global_shortcut_default():
    r = make_router()
    assert route_message("攻击2", mk_ctx(r, command_mode="global_shortcut")).kind == ROUTE_COMMAND


def test_non_whitelisted_command_bare_ignored():
    """whitelisted=False 指令不参与白名单匹配。"""
    r = make_router()
    res = route_message("内部", mk_ctx(r))
    assert res.kind == ROUTE_IGNORED
    # 带 / 前缀也需白名单存在才命中 → 仍忽略
    assert route_message("/内部", mk_ctx(r)).kind == ROUTE_IGNORED


def test_require_at_toggle_tc21():
    """TC-21：require_at 默认关直接发；开启后需 @机器人 才触发（快捷名同样跟随）。"""
    r = make_router()
    # 默认关：直接发
    assert route_message("攻击2", mk_ctx(r)).kind == ROUTE_COMMAND
    # 开启：无 @ → 忽略
    ctx = mk_ctx(r, require_at=True, shortcuts={"1": "攻击"})
    assert route_message("攻击2", ctx).kind == ROUTE_IGNORED
    assert route_message("攻击2", ctx).reason == "require_at_miss"
    # @机器人 攻击2 → 命中
    assert route_message("@机器人 攻击2", ctx).kind == ROUTE_COMMAND
    # 快捷名同样跟随（@机器人 1）
    res = route_message("@机器人 1", ctx)
    assert res.kind == ROUTE_SHORTCUT
    assert res.shortcut_command == "攻击"


def test_route_result_display_name_fallbacks():
    r = make_router()
    assert route_message("攻击", mk_ctx(r)).display_name == "攻击"
    ignored = route_message("xyz", mk_ctx(r))
    assert ignored.ignored is True
    assert ignored.display_name == "xyz"


# ===========================================================================
# 六、GM 禁绑与快捷绑定校验（3c §4.3 C01-C03/C05 + E03）
# ===========================================================================

def test_tc29_gm_forbidden_binding_c02():
    """TC-29：『快捷绑定 重载 攻击』目标为 GM 指令 → 拒绝（防权限绕过）。"""
    r = make_router()
    verdict = check_shortcut_binding("重载", "攻击", registry=r, reserved_words=FIXED_SUBWORDS)
    assert verdict["ok"] is False
    assert verdict["code"] == "name_conflict"

    verdict = check_shortcut_binding("x", "重载", registry=r, reserved_words=FIXED_SUBWORDS)
    assert verdict["ok"] is False
    assert verdict["code"] == "gm_forbidden"
    assert "GM 指令" in verdict["message"]
    assert "重载" in verdict["message"]


def test_gm_forbidden_via_alias_target():
    """绑定目标经别名指向 GM 指令 → 同样拒绝。"""
    r = make_router()
    aliases = {"重载": {"alias": "刷新", "keep_original": True}}
    verdict = check_shortcut_binding("x", "刷新", registry=r, aliases=aliases)
    assert verdict["ok"] is False
    assert verdict["code"] == "gm_forbidden"


def test_tc28_shortcut_name_conflict_c01():
    """TC-28：绑定名=现有指令 → 拒绝（动态注册表：框架+内容包+固定子词）。"""
    r = make_router()
    verdict = check_shortcut_binding("攻击", "防御", registry=r)
    assert verdict["ok"] is False
    assert verdict["code"] == "name_conflict"
    assert "换个快捷名" in verdict["message"]
    # 别名名也在冲突域
    aliases = {"锻造": "炼器"}
    verdict = check_shortcut_binding("炼器", "防御", registry=r, aliases=aliases)
    assert verdict["code"] == "name_conflict"
    # 固定子词冲突
    verdict = check_shortcut_binding("预览", "防御", registry=r, reserved_words=FIXED_SUBWORDS)
    assert verdict["code"] == "name_conflict"


def test_shortcut_binding_ok_and_format_hint_c03():
    """合法绑定通过；含空格/保留字符 → 提示不拦截（C03，只建议不限制）。"""
    r = make_router()
    assert check_shortcut_binding("火球", "攻击3", registry=r)["ok"] is True
    hint = check_shortcut_binding("火 球", "攻击3", registry=r)
    assert hint["ok"] is True
    assert hint["code"] == "name_format_hint"
    assert hint["hint"]


def test_shortcut_binding_empty_name():
    verdict = check_shortcut_binding("", "攻击", registry=make_router())
    assert verdict["ok"] is False
    assert verdict["code"] == "empty_name"


def test_tc30_shortcut_limit_e03():
    """TC-30/E03：上限默认 20（0=不限）。"""
    assert check_shortcut_limit(20)["code"] == "shortcut_full"
    assert check_shortcut_limit(19)["ok"] is True
    assert check_shortcut_limit(20, limit=0)["ok"] is True
    assert check_shortcut_limit(999, limit=0)["ok"] is True


def test_is_gm_command_helper():
    r = make_router()
    assert is_gm_command("重载", registry=r) is True
    assert is_gm_command("/重载 配置", registry=r) is True
    assert is_gm_command("攻击 2", registry=r) is False
    assert is_gm_command("重载", gm_commands={"重载", "封禁"}) is True
    assert is_gm_command("攻击", gm_commands={"重载"}) is False


def test_resolve_command_word_helper():
    r = make_router()
    assert resolve_command_word("攻击 2", registry=r) == "攻击"
    assert resolve_command_word("/重载 x", registry=r) == "重载"
    assert resolve_command_word("炼丹", registry=r,
                                aliases={"炼金": {"alias": "炼丹", "keep_original": False}}) == "炼金"
    assert resolve_command_word("不存在的话", registry=r) is None


# ===========================================================================
# 七、路由结果组合 / 边界
# ===========================================================================

def test_empty_and_whitespace_ignored():
    r = make_router()
    for inp in ("", "   ", "/", "@机器人"):
        res = route_message(inp, mk_ctx(r))
        assert res.kind == ROUTE_IGNORED, inp


def test_longest_whitelist_prefix_wins():
    r = Router()
    r.register(CommandSpec("攻击"))
    r.register(CommandSpec("攻击连击"))
    res = route_message("攻击连击3", mk_ctx(r))
    assert res.kind == ROUTE_COMMAND
    assert res.command == "攻击连击"
    assert res.args_text == "3"


def test_shortcut_before_alias_before_whitelist_priority():
    """A08：快捷表 → 指令别名 → 指令白名单 优先级写死。"""
    r = make_router()
    # 同一触发词并存三者：优先快捷（完整消息精确匹配）
    ctx = mk_ctx(r, shortcuts={"攻击": "防御"}, aliases={"防御": "攻击"})
    res = route_message("攻击", ctx)
    assert res.kind == ROUTE_SHORTCUT
    assert res.shortcut_command == "防御"
    # 去掉快捷 → 别名优先于白名单（『攻击』是『防御』的别名）
    ctx2 = mk_ctx(r, aliases={"防御": "攻击"})
    res2 = route_message("攻击", ctx2)
    assert res2.kind == ROUTE_ALIAS
    assert res2.command == "防御"


def test_route_and_expand_session_not_retriggered_on_expansion():
    """S7：快捷展开后从指令名层续走，不再触发会话路由。"""
    r = make_router()
    ctx = mk_ctx(r, dialog_active=True, shortcuts={"1": "继续"})
    res = route_and_expand("1", ctx)
    # 原始输入是会话子词（R1 优先）→ 直接送会话，不展开
    assert res.kind == ROUTE_SESSION
    assert res.subword == (SESSION_SUBWORD_DIGIT, 1)
