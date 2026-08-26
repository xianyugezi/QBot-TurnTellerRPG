"""M4 批次1·路B1：指令解析器 parsers.py 单元测试。

依据：
  - m4_shared_contract §2.1（解析管线 / 分隔符全集 / 快捷三模式 / 会话路由判定）
  - 细化_3c_指令解析契约 §1-§4 + §六 TC-01~45（验收矩阵）
  - docs/审查参考/指令分隔符统一规范.md v1.1（权威）
  - 2026-08-27 裁决①（P0-1）：战斗中裸数字 = 快捷绑定（无会话上下文，快捷表生效），
    不送战斗状态机；选技能用带指令词「/攻击 2」（序号不带 *）

断言分组（对齐 TC 矩阵）：
  TestSpaceParsing   TC-01 空格分参数 / 位置参数 ≤2
  TestQuantity       TC-02/03/05/06/07 * 数量（含旧空格兼容、/强化 禁止、上限、非数字）
  TestList           TC-08/09 , 列表（全角/半角等价）
  TestKeyValue       TC-10 = 键值（含内嵌数量）
  TestPositionalLimit TC-11 第 3 参数起强制列表/键值（超参）
  TestLevelSeqPath   TC-12/13/14 + 等级 / - 连招区间 / > 路径
  TestCompact        TC-17/18/19/45 紧凑+空格双认 / 紧凑回写 / 粘合永久兼容
  TestModes          TC-20/21/22 三模式 / require_at / 防误触 / GM 强制前缀
  TestShortcut       TC-24/25/L153/S7 快捷绑定 / 完整串展开 / 精确匹配 / 深度上限
  TestAlias          TC-33 指令别名 / keep_original:false 隐藏
  TestSessionRoute   TC-36/37/38/41 会话路由判定（只标记语义不接状态机）
  TestBattleRuling   裁决① 战斗裸数字 = 快捷表，不送会话
  TestFixedSubword   TC-42 固定子词优先
  TestErrors         TC-44 四类错误 + TC-15 保留字符黄色提示（不拦截）
  TestNamePriority   TC-43 * 左侧名称形态（语义归消费系统）
  TestParseInt       安全整数解析

铁律：零 NoneBot import；纯逻辑断言；确定性。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands.parsers import (
    ERR_MISSING,
    ERR_RESERVED,
    ERR_TOO_MANY,
    ERR_UNKNOWN_SEP,
    FIXED_SUBWORDS,
    MODE_ALIAS,
    MODE_ALIAS_HIDDEN,
    MODE_COMBAT_SHORTCUT,
    MODE_GLOBAL_SHORTCUT,
    MODE_IGNORED,
    MODE_NORMAL,
    MODE_PREFIX_ONLY,
    MODE_SESSION,
    MODE_SHORTCUT,
    ParsedCommand,
    is_session_subword,
    parse_command,
    parse_int,
    reserved_char_hint,
)


# ---------------------------------------------------------------------------
# ① 分隔符全集
# ---------------------------------------------------------------------------


class TestSpaceParsing:
    """TC-01 空格分参数（唯一参数分隔符）。"""

    def test_two_positional_args(self):
        p = parse_command("/镶嵌 火珠 铁剑")
        assert p.command == "镶嵌"
        assert p.args == ["火珠", "铁剑"]
        assert p.positional == ["火珠", "铁剑"]
        assert p.tokens == ["镶嵌", "火珠", "铁剑"]
        assert p.mode == MODE_NORMAL

    def test_single_arg(self):
        p = parse_command("/攻击 2")
        assert p.command == "攻击"
        assert p.args == ["2"]

    def test_raw_preserved(self):
        p = parse_command("  /攻击 2  ")
        assert p.raw == "  /攻击 2  "
        assert p.command == "攻击"
        assert p.args == ["2"]


class TestQuantity:
    """铁律 1：数量 = `*`（* 后必须纯数字）。"""

    def test_star_quantity(self):  # TC-03
        p = parse_command("/使用 经验药水*10")
        assert p.command == "使用"
        assert p.args == ["经验药水*10"]
        assert p.qty == 10

    def test_star_quantity_buy(self):  # TC-03
        p = parse_command("/购买 药水*5")
        assert p.args == ["药水*5"]
        assert p.qty == 5

    def test_no_star_is_sequence_not_quantity(self):  # TC-04
        p = parse_command("/攻击 2")
        assert p.args == ["2"]
        assert p.qty is None  # 序号（2 号技能），非数量

    def test_quantity_limit_hint_not_block(self):  # TC-06
        p = parse_command("/使用 经验药水*200")
        assert p.qty == 200
        assert p.error is None  # 不拦截
        assert any("最多一次使用 99 个" in h for h in p.hints)

    def test_quantity_limit_custom(self):  # 可配上限
        p = parse_command("/使用 经验药水*500", max_qty=1000)
        assert p.qty == 500
        assert not any("最多一次使用" in h for h in p.hints)

    def test_star_non_digit_error(self):  # TC-07
        p = parse_command("/使用 药水*abc")
        assert p.error == ERR_UNKNOWN_SEP
        assert p.qty is None

    def test_qianghua_forbids_star(self):  # TC-05
        p = parse_command("/强化 铁剑*3")
        assert p.error == ERR_UNKNOWN_SEP
        assert any("不使用数量" in h for h in p.hints)

    def test_old_space_quantity_compat(self):  # TC-02
        p = parse_command("/使用 药水 10")
        assert p.args == ["药水"]
        assert p.qty == 10
        assert any("下次可以这样写：使用 药水*10" in h for h in p.hints)

    def test_old_space_quantity_not_for_attack(self):  # L35 序号不带 *
        p = parse_command("/攻击 2")
        assert p.args == ["2"]
        assert p.qty is None


class TestList:
    """铁律 2：列表 = `,`（全角/半角等价）。"""

    def test_comma_list(self):  # TC-08
        p = parse_command("/投料 赤铁矿,火药,硫磺粉")
        assert p.targets == ["赤铁矿", "火药", "硫磺粉"]
        assert p.args == ["赤铁矿,火药,硫磺粉"]

    def test_fullwidth_comma_equivalent(self):  # TC-09
        p = parse_command("/投料 赤铁矿，火药")
        assert p.targets == ["赤铁矿", "火药"]

    def test_trait_with_percent(self):  # D03 词条数值允许 %
        p = parse_command("/继承 灼烧强化,回复量+5%")
        assert p.targets == ["灼烧强化", "回复量+5%"]
        assert p.error is None
        assert p.level is None  # "+5%" 非纯数字后缀，不作等级


class TestKeyValue:
    """铁律 3 键值 = `=`（值可再含 `*` 数量）。"""

    def test_kv_with_inner_quantity(self):  # TC-10
        p = parse_command("/雇工 助手名 代采=矿石*5,代调=药剂*2")
        assert p.args == ["助手名"]
        assert p.kv == [
            {"key": "代采", "value": "矿石", "qty": 5},
            {"key": "代调", "value": "药剂", "qty": 2},
        ]

    def test_kv_plain(self):  # D04 触媒=爆裂壶
        p = parse_command("/使用 触媒=爆裂壶")
        assert p.kv == [{"key": "触媒", "value": "爆裂壶", "qty": None}]

    def test_kv_list_multiple(self):
        p = parse_command("/雇工 助手名 代采=矿石*5 代调=药剂*2")
        assert p.args == ["助手名"]
        assert len(p.kv) == 2


class TestPositionalLimit:
    """铁律 3：第 3 参数起强制列表/键值（TC-11）。"""

    def test_third_plain_param_overflows(self):
        p = parse_command("/锻造 炎剑Ⅱ 预览 特殊")
        assert p.error == ERR_TOO_MANY
        assert p.fixed_subword == "预览"

    def test_third_kv_param_ok(self):
        p = parse_command("/雇工 助手名 代采=矿石*5")
        assert p.error is None
        assert p.args == ["助手名"]
        assert len(p.kv) == 1

    def test_three_plain_params_overflows(self):
        p = parse_command("/镶嵌 火珠 铁剑 龙鳞")
        assert p.error == ERR_TOO_MANY


class TestLevelSeqPath:
    """后置修饰：+ 等级 / - 连招区间 / > 路径。"""

    def test_level_suffix(self):  # TC-12
        p = parse_command("/强化 铁剑+5")
        assert p.level == 5
        assert p.args == ["铁剑+5"]
        assert p.error is None

    def test_level_trait(self):  # TC-12 词条 攻击+3
        p = parse_command("/继承 攻击+3")
        assert p.level == 3

    def test_seq_chain(self):  # TC-13 连招序列
        p = parse_command("/攻击 1-2-3")
        assert p.seq == [1, 2, 3]

    def test_seq_range_expand(self):  # TC-13 区间展开
        p = parse_command("/背包 1-3")
        assert p.seq == [1, 2, 3]

    def test_seq_range_five(self):  # S2 区间语义
        p = parse_command("/背包 1-5")
        assert p.seq == [1, 2, 3, 4, 5]

    def test_name_with_dash_not_seq(self):  # N02 `-` 允许名字符
        p = parse_command("/使用 AB-CD")
        assert p.seq == []
        assert p.error is None

    def test_path_forge(self):  # TC-14 派生链
        p = parse_command("/锻造 铁剑>铁剑Ⅱ")
        assert p.path == ["铁剑", "铁剑Ⅱ"]

    def test_path_enter(self):  # TC-14 连续移动
        p = parse_command("/进入 1>2")
        assert p.path == ["1", "2"]


class TestCompact:
    """紧凑 + 空格双认（TC-17/18/19/45）。"""

    def test_compact_digit(self):  # TC-17
        p = parse_command("攻击2")
        assert p.command == "攻击"
        assert p.args == ["2"]
        assert p.compact is True

    def test_space_equivalent(self):  # TC-18
        pc = parse_command("攻击2")
        ps = parse_command("攻击 2")
        assert pc.command == ps.command
        assert pc.args == ps.args

    def test_compact_item_qty(self):  # TC-17
        p = parse_command("使用经验药水*10")
        assert p.command == "使用"
        assert p.args == ["经验药水*10"]
        assert p.qty == 10
        assert p.compact is True

    def test_compact_direction(self):  # TC-17 汉字=方向/名称
        p = parse_command("进入上")
        assert p.command == "进入"
        assert p.args == ["上"]
        assert p.compact is True

    def test_compact_digit_enter(self):  # TC-17
        p = parse_command("进入2")
        assert p.command == "进入"
        assert p.args == ["2"]

    def test_space_hint_compact(self):  # TC-19
        p = parse_command("攻击 2")
        assert any("下次可以这样写：攻击2" in h for h in p.hints)

    def test_compact_no_hint(self):
        p = parse_command("攻击2")
        assert not any(h.startswith("下次可以这样写") for h in p.hints)


class TestModes:
    """command_mode 三模式 + require_at + 防误触。"""

    def test_global_default_unprefixed_ok(self):  # 默认全局免前缀
        p = parse_command("攻击2")
        assert p.command == "攻击"
        assert p.prefix_stripped is False

    def test_prefix_only_requires_slash(self):  # TC-20
        p = parse_command("攻击 2", command_mode=MODE_PREFIX_ONLY)
        assert p.mode == MODE_IGNORED
        p2 = parse_command("/攻击 2", command_mode=MODE_PREFIX_ONLY)
        assert p2.command == "攻击"

    def test_prefix_only_shortcut_with_slash(self):  # L177 prefix_only 发 '/1'
        p = parse_command("/1", command_mode=MODE_PREFIX_ONLY, shortcuts={"1": "攻击"})
        assert p.mode == MODE_SHORTCUT
        assert p.command == "攻击"
        assert p.prefix_stripped is True

    def test_prefix_only_unprefixed_shortcut_ignored(self):  # L177 免前缀 1 不触发
        p = parse_command("1", command_mode=MODE_PREFIX_ONLY, shortcuts={"1": "攻击"})
        assert p.mode == MODE_IGNORED

    def test_combat_shortcut_in_battle(self):  # TC-20
        p = parse_command("攻击2", command_mode=MODE_COMBAT_SHORTCUT, in_battle=True)
        assert p.command == "攻击"
        p2 = parse_command("攻击2", command_mode=MODE_COMBAT_SHORTCUT, in_battle=False)
        assert p2.mode == MODE_IGNORED
        p3 = parse_command("/攻击 2", command_mode=MODE_COMBAT_SHORTCUT, in_battle=False)
        assert p3.command == "攻击"

    def test_require_at_default_off(self):  # TC-21
        p = parse_command("攻击2")
        assert p.command == "攻击"

    def test_require_at_on(self):  # TC-21
        p = parse_command("攻击2", require_at=True)
        assert p.mode == MODE_IGNORED
        p2 = parse_command("@机器人 攻击2", require_at=True)
        assert p2.command == "攻击"
        assert p2.prefix_stripped is False  # 剥离的是 @提及

    def test_require_at_shortcut_follows(self):  # TC-21 / L178
        p = parse_command("@机器人 1", require_at=True, shortcuts={"1": "攻击"})
        assert p.mode == MODE_SHORTCUT
        assert p.command == "攻击"

    def test_random_text_ignored(self):  # TC-22 防误触
        p = parse_command("今天天气真好")
        assert p.mode == MODE_IGNORED
        assert p.command is None

    def test_gm_force_prefix(self):  # TC-22 / L128 GM 永不快捷
        p = parse_command("重载")
        assert p.mode == MODE_IGNORED
        p2 = parse_command("/重载")
        assert p2.command == "重载"

    def test_dialog_prefix_required(self):  # m4 §2.3 接缝裁决：/对话 不可免前缀直发
        p = parse_command("对话")
        assert p.mode == MODE_IGNORED
        p2 = parse_command("/对话")
        assert p2.command == "对话"

    def test_non_whitelist_command_ignored(self):  # W04 保留前缀推荐
        p = parse_command("开始")
        assert p.mode == MODE_IGNORED


class TestShortcut:
    """快捷绑定（规范 6.6）：完整消息精确匹配 / 完整指令串展开 / 深度上限。"""

    def test_bind_with_arg(self):  # TC-24
        p = parse_command("火球", shortcuts={"火球": "攻击3"})
        assert p.mode == MODE_SHORTCUT
        assert p.command == "攻击"
        assert p.args == ["3"]
        assert p.expand_count == 1
        assert p.raw == "火球"

    def test_bind_full_command_str(self):  # TC-25
        p = parse_command("奶", shortcuts={"奶": "使用治疗药水*2"})
        assert p.mode == MODE_SHORTCUT
        assert p.command == "使用"
        assert p.args == ["治疗药水*2"]
        assert p.qty == 2

    def test_exact_match_only(self):  # L153 攻击2 不受快捷 1 影响
        p = parse_command("攻击2", shortcuts={"1": "攻击"})
        assert p.mode == MODE_NORMAL
        assert p.command == "攻击"
        assert p.args == ["2"]

    def test_expand_no_recurse_loop(self):  # S7 裁决：展开深度 ≤1
        p = parse_command("a", shortcuts={"a": "b", "b": "a"})
        assert p.expand_count == 1  # 展开深度 ≤1，无 A→B→A 死循环
        assert p.mode == MODE_SHORTCUT  # 触发来源=快捷
        assert p.command is None  # "b" 非白名单指令 → 不可执行（command=None）

    def test_shortcut_expand_session_active_not_routed(self):
        # 快捷展开后带指令词（"攻击3"）→ 正常解析，不送会话
        p = parse_command("火球", shortcuts={"火球": "攻击3"}, session_active=True)
        assert p.command == "攻击"
        assert p.mode == MODE_SHORTCUT

    def test_shortcut_none(self):  # TC-41 未绑定裸数字
        p = parse_command("1")
        assert p.mode == MODE_IGNORED


class TestAlias:
    """指令别名（规范 6.7 / TC-33）。"""

    ALIASES = {
        "炼金": {"alias": "炼丹", "keep_original": False},
        "锻造": "炼器",  # 默认 keep_original:true
    }

    def test_alias_resolves(self):
        p = parse_command("炼丹", aliases=self.ALIASES)
        assert p.mode == MODE_ALIAS
        assert p.command == "炼金"
        assert p.display_name == "炼丹"

    def test_alias_with_args(self):  # 炼丹 火灵丹*3 = 炼金 火灵丹*3
        p = parse_command("炼丹 火灵丹*3", aliases=self.ALIASES)
        assert p.mode == MODE_ALIAS
        assert p.command == "炼金"
        assert p.args == ["火灵丹*3"]
        assert p.qty == 3

    def test_hidden_original_guides(self):  # keep_original:false → 引导提示
        p = parse_command("炼金", aliases=self.ALIASES)
        assert p.mode == MODE_ALIAS_HIDDEN
        assert p.command is None
        assert p.alias_hidden == "炼金"
        assert any("试试『炼丹』" in h for h in p.hints)

    def test_keep_original_true_keeps_both(self):
        p = parse_command("锻造", aliases=self.ALIASES)
        assert p.command == "锻造"
        assert p.mode == MODE_NORMAL


class TestSessionRoute:
    """会话路由判定（只标记语义不接状态机）：TC-36/37/38/41。"""

    def test_dialog_digit_routes(self):  # TC-36
        p = parse_command("2", session_active=True)
        assert p.mode == MODE_SESSION
        assert p.session_candidate is True
        assert p.session_route is True
        assert p.command is None

    def test_dialog_continue_routes(self):
        p = parse_command("继续", session_active=True)
        assert p.mode == MODE_SESSION
        assert p.session_candidate is True

    def test_dialog_exit_words(self):  # 退出/离开/再见
        for w in ("退出", "离开", "再见"):
            p = parse_command(w, session_active=True)
            assert p.mode == MODE_SESSION, w

    def test_dialog_select_n(self):
        for s in ("选择 3", "选择3"):
            p = parse_command(s, session_active=True)
            assert p.mode == MODE_SESSION, s

    def test_session_priority_over_shortcut(self):  # TC-38 R3
        p = parse_command("1", session_active=True, shortcuts={"1": "攻击"})
        assert p.mode == MODE_SESSION
        assert p.command is None

    def test_command_word_normal_parse_in_dialog(self):  # TC-37 R2
        p = parse_command("使用1", session_active=True)
        assert p.command == "使用"
        assert p.mode == MODE_NORMAL
        p2 = parse_command("背包2", session_active=True)
        assert p2.command == "背包"

    def test_no_session_shortcut_active(self):  # TC-41 R4
        p = parse_command("1", session_active=False, shortcuts={"1": "攻击"})
        assert p.mode == MODE_SHORTCUT
        assert p.command == "攻击"

    def test_is_session_subword_helper(self):
        assert is_session_subword("3") is True
        assert is_session_subword("继续") is True
        assert is_session_subword("选择 2") is True
        assert is_session_subword("攻击2") is False
        assert is_session_subword("你好") is False


class TestBattleRuling:
    """2026-08-27 裁决①：战斗中裸数字 = 快捷表（无会话上下文），不送战斗状态机。"""

    def test_battle_naked_digit_bound_shortcut(self):
        p = parse_command("1", in_battle=True, shortcuts={"1": "攻击"})
        assert p.mode == MODE_SHORTCUT
        assert p.command == "攻击"
        assert p.mode != MODE_SESSION

    def test_battle_naked_digit_unbound_ignored(self):
        p = parse_command("3", in_battle=True)
        assert p.mode == MODE_IGNORED
        assert p.command is None
        assert p.session_candidate is False

    def test_battle_continue_exit_not_session(self):
        # 裁决删除 3c §5.2 战斗侧会话路由：继续/退出 无会话上下文 → 走正常管线（忽略）
        for w in ("继续", "退出", "选择 2"):
            p = parse_command(w, in_battle=True)
            assert p.mode == MODE_IGNORED, w
            assert p.session_candidate is False, w

    def test_battle_command_word_parses(self):  # 选技能用带指令词 /攻击 2
        p = parse_command("/攻击 2", in_battle=True)
        assert p.command == "攻击"
        assert p.args == ["2"]

    def test_battle_session_active_defensive(self):
        # 防御性：即使误传 session_active=True，战斗中也不送会话（裁决①）
        p = parse_command("2", in_battle=True, session_active=True, shortcuts={"2": "防御"})
        assert p.mode == MODE_SHORTCUT
        assert p.command == "防御"


class TestFixedSubword:
    """固定子词优先于物品匹配（TC-42 / L71）。"""

    def test_auto_subword(self):
        p = parse_command("/炼金 火焰弹 自动")
        assert p.command == "炼金"
        assert p.args == ["火焰弹"]
        assert p.fixed_subword == "自动"

    def test_preview_subword(self):
        p = parse_command("/锻造 炎剑Ⅱ 预览")
        assert p.fixed_subword == "预览"
        assert p.args == ["炎剑Ⅱ"]

    def test_subword_not_positional(self):
        p = parse_command("/炼金 火焰弹 自动")
        assert "自动" not in p.args

    def test_fixed_subword_set(self):
        assert FIXED_SUBWORDS == {"追加", "预览", "自动", "查看", "确认", "放弃", "续"}


class TestErrors:
    """四类错误模板（TC-44）+ 保留字符黄色提示（TC-15，不拦截）。"""

    SPECS = {"攻击": {"min_args": 1}}

    def test_missing_arg(self):  # 缺参（需 command_specs 声明）
        p = parse_command("/攻击", command_specs=self.SPECS)
        assert p.error == ERR_MISSING
        assert p.command == "攻击"

    def test_missing_arg_not_with_arg(self):
        p = parse_command("/攻击 2", command_specs=self.SPECS)
        assert p.error is None

    def test_too_many(self):  # 超参
        p = parse_command("/锻造 炎剑Ⅱ 预览 特殊")
        assert p.error == ERR_TOO_MANY

    def test_unknown_separator(self):  # 未知分隔符（！/％/# 等未登记符号）
        p = parse_command("/使用 火！石")
        assert p.error == ERR_UNKNOWN_SEP
        p2 = parse_command("/使用 火％石")
        assert p2.error == ERR_UNKNOWN_SEP

    def test_reserved_char_hint_not_block(self):  # TC-15 只建议不限制
        p = parse_command("/使用 AB+C")
        assert p.error is None
        assert any("保留字符" in h for h in p.hints)

    def test_reserved_char_hint_space(self):  # 物品名禁空格（N01）
        hint = reserved_char_hint("暴击 药剂")
        assert hint is not None
        assert "空格" in hint

    def test_reserved_char_hint_allowed_name(self):  # TC-16 允许字符
        assert reserved_char_hint("炎剑Ⅱ") is None
        assert reserved_char_hint("炼狱爆弹·改") is None

    def test_unknown_sep_slash(self):
        p = parse_command("/使用 a/b")
        assert p.error == ERR_UNKNOWN_SEP


class TestNamePriority:
    """名称优先（TC-43 / L70）：* 左侧存名称形态，名称/序号解析归消费系统。"""

    def test_star_left_side_is_name_form(self):
        p = parse_command("/使用 药水*10")
        assert p.args == ["药水*10"]  # 左侧名称形态，qty 独立提取
        assert p.qty == 10

    def test_no_star_sequence(self):  # 无 * = 序号/名称
        p = parse_command("/攻击 2")
        assert p.args == ["2"]
        assert p.qty is None


class TestParseInt:
    """parse_int 安全整数解析（3d §2.2）。"""

    def test_valid(self):
        assert parse_int("12") == 12
        assert parse_int("-3") == -3
        assert parse_int("+7") == 7
        assert parse_int(" 5 ") == 5

    def test_invalid(self):
        assert parse_int("abc") is None
        assert parse_int("1.5") is None
        assert parse_int("12a") is None
        assert parse_int("") is None
        assert parse_int("   ") is None
        assert parse_int(None) is None


class TestMisc:
    """ParsedCommand 便捷接口。"""

    def test_arg_accessor(self):
        p = parse_command("/镶嵌 火珠 铁剑")
        assert p.arg(0) == "火珠"
        assert p.arg(1) == "铁剑"
        assert p.arg(2, default="无") == "无"

    def test_equality(self):
        a = parse_command("攻击2")
        b = parse_command("攻击2")
        assert a == b

    def test_is_command(self):
        assert parse_command("/攻击 2").is_command is True
        assert parse_command("今天天气真好").is_command is False
        assert parse_command("2", session_active=True).is_command is False

    def test_explicit_slash_always_allowed(self):
        p = parse_command("/攻击 2", command_mode=MODE_PREFIX_ONLY)
        assert p.command == "攻击"
        assert p.prefix_stripped is True
