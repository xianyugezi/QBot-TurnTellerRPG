"""注册指令单测（M6 批次1·路B · qbot_rpg/commands/register_commands.py）——TC-REG-01~05 全量。

依据：细化_M6_三引擎与基础指令（D1）§四（REG-01~REG-06 / TC-REG-01~05，承接 4f
TC-01/02/03/04/06）+ 细化_4f §一（RUL-01~09 / TPL-4F-01）+ 细化_3d（TPL-12 / emoji 纪律）。

测试风格对齐 tests/unit/test_basic_commands.py：make_ctx 模式、纯 pytest、零 NoneBot、
断言具体输出字符串。渲染仅 ✅/❌ 功能性标记（M5 裁决「不用 emoji」：4f 示例 🟢 推荐角标
降级为纯文本「（推荐新手）」）。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands import register_commands as rc
from qbot_rpg.commands.parsers import ParsedCommand, parse_command
from qbot_rpg.commands.register_commands import (
    REGISTER_CMD,
    TPL_ALREADY_REGISTERED,
    TPL_DUP_NAME,
    TPL_JOB_NOT_FOUND,
    TPL_NAME_TOO_LONG,
    build_initial_player,
    cmd_register,
    default_job,
    register_register_commands,
    resolve_job,
)
from qbot_rpg.commands.router import Router

# 3d §4.2 装饰性 emoji 禁用清单（渲染输出扫描锚点）
BANNED_EMOJI = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")

# 职业表（jobs.json 语义：recommended_newbie 推荐角标，L591）
_JOBS = {
    "warrior": {"name": "战士", "recommended_newbie": True},
    "mage": {"name": "法师", "recommended_newbie": True},
    "ranger": {"name": "游侠", "recommended_newbie": False},
}

# 属性模板（stats.json 语义：hp 100/mp 30/战斗 10~15，L608-611）
_STATS = {
    "hp": {"name": "生命", "type": "resource", "base": 100},
    "mp": {"name": "魔力", "type": "resource", "base": 30},
    "str": {"name": "力量", "type": "combat", "base": 12},
    "con": {"name": "体质", "type": "combat", "base": 10},
    "int": {"name": "智力", "type": "combat", "base": 10},
    "agi": {"name": "敏捷", "type": "combat", "base": 10},
}


def make_ctx(**over):
    """未注册玩家基础 ctx（每场景新造；registered=False 为注册场景默认）。"""
    base = {
        "registered": False,
        "player": None,
        "jobs": {k: dict(v) for k, v in _JOBS.items()},
        "stats": {k: dict(v) for k, v in _STATS.items()},
        "settings": {"default_job_id": "warrior", "default_map": "新手村", "world_name": "艾泽拉"},
        "name_exists": lambda name: False,
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    """parse_command 封装（parsers.DEFAULT_WHITELIST 已含「注册」）。"""
    return parse_command(raw)


# ---------------------------------------------------------------------------
# TC-REG-01 首次注册成功（承接 4f TC-01）
# ---------------------------------------------------------------------------

def test_tc_reg_01_first_register_success():
    """TC-REG-01：`注册 阿伟 战士` → 前缀首行 + ✅ 注册成功 + 职业/位置/初始属性 + 引导行。"""
    ctx = make_ctx()
    out = cmd_register(parse("/注册 阿伟 战士"), ctx)
    lines = out.splitlines()
    assert lines[0] == "Lv1.阿伟 - -"                                  # 前缀首行
    assert "✅ 注册成功！欢迎来到「艾泽拉」世界" in out
    assert "职业：战士（推荐新手） ｜ 位置：新手村" in out              # 推荐角标降级纯文本
    # 意见一同步：初始属性每项独立一行（生命/魔力/攻击/防御各一行）
    assert "初始属性：\n生命 100/100\n魔力 30/30\n攻击 12\n防御 10" in out
    assert "下一步：发 /帮助 查看指令，或 /锁定 新手村怪物开战。" in out
    # 建号状态写 ctx（REG-04/05）
    assert ctx["registered"] is True
    p = ctx["player"]
    assert p["name"] == "阿伟" and p["job_id"] == "warrior"
    assert p["level"] == 1 and p["exp"] == 0
    assert p["hp"] == 100 and p["mp"] == 30
    assert p["inventory"] == [] and p["equipment"] == {}
    assert ctx["location"] == "新手村"


def test_tc_reg_01_after_status_queryable():
    """TC-REG-01 后半：注册成功后 /状态 可查询（无注册拦截）。"""
    ctx = make_ctx()
    cmd_register(parse("/注册 阿伟 战士"), ctx)
    assert ctx["registered"] is True
    assert ctx["player"]["name"] == "阿伟"


# ---------------------------------------------------------------------------
# TC-REG-02 缺省职业兜底（承接 4f TC-02 / B7）
# ---------------------------------------------------------------------------

def test_tc_reg_02_default_job_fallback():
    """TC-REG-02：`注册 小明` → 缺省职业 = settings.default_job_id（战士），明示推荐。"""
    ctx = make_ctx()
    out = cmd_register(parse("/注册 小明"), ctx)
    assert "✅ 注册成功！" in out
    assert "职业：战士（推荐新手）" in out
    assert ctx["player"]["job_id"] == "warrior"


def test_tc_reg_02_no_default_job_takes_first_recommended():
    """B7 兜底链 ①：settings 无 default_job_id → 首个 recommended_newbie 职业。"""
    jobs = {
        "warrior": {"name": "战士", "recommended_newbie": False},
        "mage": {"name": "法师", "recommended_newbie": True},
    }
    ctx = make_ctx(jobs={k: dict(v) for k, v in jobs.items()},
                   settings={"default_map": "新手村", "world_name": "艾泽拉"})
    out = cmd_register(parse("/注册 小明"), ctx)
    assert "职业：法师（推荐新手）" in out          # mage 是首个 recommended_newbie
    assert ctx["player"]["job_id"] == "mage"


def test_tc_reg_02_no_recommended_takes_first_job():
    """B7 兜底链 ②：无 recommended_newbie → jobs 首职业（游侠）。"""
    jobs = {
        "ranger": {"name": "游侠", "recommended_newbie": False},
        "thief": {"name": "盗贼", "recommended_newbie": False},
    }
    ctx = make_ctx(jobs={k: dict(v) for k, v in jobs.items()},
                   settings={"default_map": "新手村"})
    out = cmd_register(parse("/注册 小明"), ctx)
    assert "职业：游侠" in out
    assert ctx["player"]["job_id"] == "ranger"


def test_tc_reg_02_invalid_default_job_id_falls_back():
    """B7 防御：default_job_id 不在 jobs 表 → 继续走推荐/首职业（不建无效职业）。"""
    ctx = make_ctx(settings={"default_job_id": "nope", "default_map": "新手村"})
    out = cmd_register(parse("/注册 小明"), ctx)
    assert "职业：战士（推荐新手）" in out
    assert ctx["player"]["job_id"] == "warrior"


def test_job_not_found_lists_available():
    """RUL-03：职业不存在 → `❌ 没有『XX』这个职业，可用：…（推荐角标）`。"""
    ctx = make_ctx()
    out = cmd_register(parse("/注册 阿伟 刺客"), ctx)
    assert out == "❌ 没有『刺客』这个职业，可用：战士（推荐） 法师（推荐） 游侠"
    assert ctx["registered"] is False and ctx["player"] is None      # 不建号


def test_default_job_and_resolve_job_pure():
    """resolve_job / default_job 纯函数：显示名精确匹配 + job_id 兜底 + 缺省链。"""
    ctx = make_ctx()
    assert resolve_job(ctx, "战士")["id"] == "warrior"
    assert resolve_job(ctx, "warrior")["id"] == "warrior"            # job_id 兜底（工程补白）
    assert resolve_job(ctx, "不存在") is None
    assert default_job(ctx)["id"] == "warrior"                       # default_job_id 优先
    # 无 default_job_id → 首个 recommended_newbie（_JOBS 中 warrior 居首）
    assert default_job(make_ctx(settings={"default_map": "新手村"}))["id"] == "warrior"
    # 无 recommended_newbie → jobs 首职业
    jobs = {"ranger": {"name": "游侠"}, "thief": {"name": "盗贼"}}
    ctx2 = make_ctx(jobs={k: dict(v) for k, v in jobs.items()}, settings={"default_map": "新手村"})
    assert default_job(ctx2)["id"] == "ranger"


# ---------------------------------------------------------------------------
# TC-REG-03 重名拦截（承接 4f TC-03 / B5）
# ---------------------------------------------------------------------------

def test_tc_reg_03_duplicate_name_blocked():
    """TC-REG-03：name_exists 回调为真 → `❌ 已经有一个叫『阿伟』的角色了，换个名字吧`；不建号。"""
    ctx = make_ctx(name_exists=lambda name: name == "阿伟")
    out = cmd_register(parse("/注册 阿伟 战士"), ctx)
    assert out == TPL_DUP_NAME.format(name="阿伟")
    assert ctx["registered"] is False and ctx["player"] is None      # 不建号、不回滚既有数据


# ---------------------------------------------------------------------------
# TC-REG-04 已注册幂等（承接 4f TC-04 / RUL-09）
# ---------------------------------------------------------------------------

def test_tc_reg_04_already_registered_idempotent():
    """TC-REG-04：已注册再 /注册 → `❌ 你已经注册过了！当前角色：…`；不覆盖原档。"""
    ctx = make_ctx(registered=True,
                   player={"name": "小李", "level": 5, "job_id": "mage"},
                   job_name="法师")
    out = cmd_register(parse("/注册 小李 法师"), ctx)
    # 2026-08-31 用户拍板：job 段不再自带空格（无职业名时整体省略，如 novice 隐藏）
    assert out == TPL_ALREADY_REGISTERED.format(name="小李", level=5, job=" 法师")
    assert ctx["player"]["name"] == "小李"                            # 原档未被覆盖
    assert ctx["player"]["level"] == 5


# ---------------------------------------------------------------------------
# TC-REG-05 名字长度/保留字符（承接 4f TC-06 / RUL-02 / 框架 L1156）
# ---------------------------------------------------------------------------

def test_tc_reg_05_name_too_long():
    """TC-REG-05：21 字名 → `❌ 角色名最多 20 个字`（框架 L1156）。"""
    name21 = "一二三四五六七八九十一二三四五六七八九十" + "一"
    ctx = make_ctx()
    out = cmd_register(parse(f"/注册 {name21} 战士"), ctx)
    assert out == TPL_NAME_TOO_LONG
    assert ctx["registered"] is False and ctx["player"] is None      # 不建号


def test_tc_reg_05_reserved_char_hint():
    """TC-REG-05：名字含保留字符（+）→ 黄提示引导换名（不硬拦，成功消息附尾缀）。

    （注：`*` 为解析器数量操作符（阿*伟 → 未知分隔符 TPL-12）；`+` 为允许名字符且触发
    保留字符黄提示，故用 `阿+伟` 驱动「不硬拦 + 附提示」路径。）
    """
    ctx = make_ctx()
    out = cmd_register(parse("/注册 阿+伟 战士"), ctx)
    assert "✅ 注册成功！" in out
    assert "名字含保留字符（* , = + /），解析时容易歧义（建议改名）" in out
    assert ctx["registered"] is True                                  # 不硬拦 → 注册成功


def test_tc_reg_05_control_chars_filtered():
    """REG-02 ②：名字含控制字符 → 硬拦过滤（安全补强 L1156）。"""
    ctx = make_ctx()
    parsed = ParsedCommand("/注册", command=REGISTER_CMD, args=["阿\u0000伟", "战士"])
    out = cmd_register(parsed, ctx)
    assert out == "❌ 角色名含非法字符，请重新输入（过滤控制字符/超长 emoji）"
    assert ctx["registered"] is False and ctx["player"] is None


# ---------------------------------------------------------------------------
# 语法 / TPL-12（REG-01 / 3d §5.1）
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["/注册", "/注册 阿伟 战士 3", "/注册 1 2 3", "/注册 阿伟 战士 4 5"])
def test_register_syntax_tpl12(raw):
    """REG-01：缺名/超参 → TPL-12（格式错误统一）。"""
    ctx = make_ctx()
    out = cmd_register(parse(raw), ctx)
    assert out.startswith("❌ 指令不正确：")


def test_register_parse_error_tpl12():
    """解析错误（未知分隔符）→ TPL-12。"""
    ctx = make_ctx()
    parsed = ParsedCommand("/注册", command=REGISTER_CMD, args=[], error="未知分隔符")
    out = cmd_register(parsed, ctx)
    assert out.startswith("❌ 指令不正确：")


def test_register_syntax_error_before_registered_check():
    """语法错误优先于幂等检查：已注册玩家发空 `注册` → TPL-12（缺参）。"""
    ctx = make_ctx(registered=True, player={"name": "小李", "level": 5, "job_id": "mage"})
    out = cmd_register(parse("/注册"), ctx)
    assert out.startswith("❌ 指令不正确：")


# ---------------------------------------------------------------------------
# 建号 / 渲染纯函数
# ---------------------------------------------------------------------------

def test_build_initial_player():
    """build_initial_player：初始属性按 stats 模板（hp/mp/战斗属性），inventory/equipment 空。"""
    p = build_initial_player(make_ctx(), "阿伟", "warrior")
    assert p["attributes"].base["hp"] == 100.0
    assert p["attributes"].base["str"] == 12.0
    assert p["hp"] == 100 and p["mp"] == 30
    assert p["equipment"] == {} and p["inventory"] == []


def test_register_no_decorative_emoji():
    """M5 裁决：注册成功/失败文案零装饰 emoji（仅 ✅/❌；🟢 推荐角标已降级纯文本）。"""
    ctx = make_ctx()
    outputs = [
        cmd_register(parse("/注册 阿伟 战士"), make_ctx()),
        cmd_register(parse("/注册 小明"), make_ctx()),
        cmd_register(parse("/注册 阿*伟"), make_ctx()),
        cmd_register(parse("/注册 阿伟 刺客"), make_ctx()),
        cmd_register(parse("/注册"), make_ctx()),
        TPL_NAME_TOO_LONG,
        TPL_ALREADY_REGISTERED,
        TPL_DUP_NAME,
        TPL_JOB_NOT_FOUND,
    ]
    for text in outputs:
        for ch in text:
            assert ch not in BANNED_EMOJI, f"命中禁用装饰 emoji：{ch} in {text!r}"


# ---------------------------------------------------------------------------
# 装配（REG-06 ①）
# ---------------------------------------------------------------------------

def test_register_register_commands():
    """REG-06 ①：注册「注册」CommandSpec（可快捷白名单）。"""
    router = Router()
    register_register_commands(router, make_context=lambda p: make_ctx())
    assert router.has(REGISTER_CMD)
    assert router.get(REGISTER_CMD).whitelisted


def test_register_without_make_context_raises():
    """【待接线】无 make_context 时 handler 调用抛 RuntimeError（装配未注入显式错误）。"""
    router = Router()
    register_register_commands(router)
    with pytest.raises(RuntimeError):
        router.get(REGISTER_CMD).handler(parse("/注册 阿伟 战士"))


def test_router_parse_integration():
    """/注册 经 parse_command + 注册后 handler 可执行（完整链路）。"""
    router = Router()
    register_register_commands(router, make_context=lambda p: make_ctx())
    out = router.get(REGISTER_CMD).handler(parse("/注册 阿伟 战士"))
    assert out.startswith("Lv1.阿伟 - -")


def test_regress_p1_1_fixed_subword_name_not_swallowed():
    """P1-1 回归（M6 批1B 审查）：`注册 自动 战士` 的 fixed_subword「自动」被解析器抽离后
    不得静默把「战士」当角色名注册——应 TPL-12 明确拒绝（角色名含会话子词无法经解析器）。"""
    out = cmd_register(parse("/注册 自动 战士"), make_ctx())
    assert out.startswith("❌ 指令不正确：/注册 自动 战士")
    # 无 job 参数同样拒绝
    out2 = cmd_register(parse("/注册 自动"), make_ctx())
    assert out2.startswith("❌ 指令不正确：/注册 自动")
