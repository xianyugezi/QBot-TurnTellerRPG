"""基础指令组接线单测（M4 批次6·路G1 · qbot_rpg/commands/basic_commands.py）。

依据：m4_shared_contract §2.3 + 4f + 裁决②
  - m4_shared_contract.md §2.3（基础指令组：/角色 /背包 /装备 /技能 /帮助，4f RUL-01~34，页码夹取
    口径）+ §2.2（列表 5 条/页上限、页脚固定 TPL-08、页码越界夹取 +「已到最后一页」2026-08-27
    用户裁决②、0/负数/非数字 → TPL-12、错误模板统一、emoji 纪律：数据型功能图标豁免）
  - docs/细化/细化_4f_基础指令组契约.md（RUL-08 注册门槛/B6 /帮助 豁免、RUL-16~19 /背包、RUL-20~25
    /帮助 分组与 GM 保密、面板三层 → /角色）
  - docs/细化/细化_3d_消息模板规范.md（TPL-08/TPL-12、5 条/页、D-01 emoji 禁令）
  - docs/细化/细化_3b_玩家属性三层.md（白值/加成/临时 → /角色 管线）
  - docs/细化/细化_6a_技能库契约.md（技能 type/mp/desc/chain_refs/job_restrict → /技能 派生指向）
  - docs/细化/细化_4b_物品与背包契约.md（INV-01~07 → /背包 行格式/acquired_at 排序）
  - 2026-08-27 用户裁决②（页码夹取最后一页；0/负数/非数字 → TPL-12）

集成口径：装备引擎 core/equipment.py（M1 骨架）未实装，本测试以**契约忠实替身**驱动——注入
ctx["equip_engine"] = FakeEquipEngine（实现本层文件头声明的消费接口 equip_wear / equip_remove），
断言命令层解析/渲染/路由/装配/错误全链路输出；装备栏渲染为纯函数直读 ctx["equipment"]，不依赖
引擎。其余命令（/角色 /背包 /技能 /帮助）为纯渲染，直接构造 ctx 驱动。

覆盖：/角色（LV 行固定头部 + 属性三层白值/加成/临时 + 5 条/页 + TPL-08 + 裁决② 夹取 + 资源型
当前/上限 + 满级头 + 0/负数/非数字 → TPL-12）· /背包（物品行 RUL-19 行格式：图标/×数量/品质/绑定 +
acquired_at 倒序 + 空背包 + 夹取 + TPL-12）· /装备（装备栏 5 条/页 + 空槽 + 页码 + 穿/卸子词 +
槽位解析值域文案 + TPL-12 + 引擎注入/待接线防御）· /技能（LV 行固定头部 + 类型/MP/描述 + 派生指向
「可派生成：XX」+ 职业过滤 + 5 条/页 + 夹取 + TPL-12）· /帮助（分组目录普通 5 组单页 / GM 6 组 2 页 +
组页指令列表 + 未注册引导版 B6 + 未知组/非法页码 TPL-12）· 注册门槛 RUL-08 · 路由注册装配 ·
页脚 TPL-08 逐字 · 无装饰 emoji。
"""

from __future__ import annotations

import pytest

import qbot_rpg.commands.basic_commands as bc
from qbot_rpg.commands.basic_commands import (
    BAG_CMD,
    EQUIP_CMD,
    HELP_CMD,
    HELP_GROUPS,
    SKILL_CMD,
    SUB_REMOVE,
    SUB_WEAR,
    TPL_EMPTY_BAG,
    TPL_NO_SLOT,
    TPL_REGISTER_GATE,
    VIEW_CMD,
    attr_line,
    bag_line,
    cmd_bag,
    cmd_equip,
    cmd_help,
    cmd_skill,
    cmd_view, cmd_view_detail,
    equip_line,
    group_page_line,
    register_basic_commands,
    resolve_equip_slot,
    skill_line,
    skill_rows,
)
from qbot_rpg.commands.parsers import ParsedCommand, parse_command
from qbot_rpg.commands.router import Router

# 3d §4.2 装饰性 emoji 禁用清单（程序化扫描锚点）
BANNED_EMOJI = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")

# ---------------------------------------------------------------------------
# 契约忠实替身：core/equipment.py（M1 骨架）消费接口
# ---------------------------------------------------------------------------

QUALITY_LABELS = {"normal": "普通", "fine": "精良", "epic": "史诗", "legendary": "传说"}
_TYPE_LABELS = {"basic": "普攻", "active": "主动", "passive": "被动", "trigger": "触发"}

# 九预置属性（3b §4.1：白值模板）
_STAT_NAMES = {
    "hp": "生命", "mp": "魔力", "str": "力量", "int": "智力", "con": "体质",
    "spr": "精神", "foc": "专注", "agi": "敏捷", "lck": "幸运",
}
_BASE = {"hp": 100, "mp": 30, "str": 15, "int": 15, "con": 10,
         "spr": 10, "foc": 10, "agi": 10, "lck": 10}

_INVENTORY = [
    {"item_id": "potion_hp", "name": "疗伤药", "count": 10, "quality": "normal",
     "bound": False, "acquired_at": "2026-08-18T09:30"},
    {"item_id": "iron_sword", "name": "铁剑", "count": 1, "quality": "fine",
     "bound": False, "acquired_at": "2026-08-18T09:35"},
    {"item_id": "quest_letter", "name": "任务信物", "count": 1, "quality": "normal",
     "bound": True, "acquired_at": "2026-08-18T09:40"},
    {"item_id": "iron_ore", "name": "铁矿", "count": 20, "quality": "normal",
     "bound": False, "acquired_at": "2026-08-18T09:45"},
    {"item_id": "cloth", "name": "粗布", "count": 1, "quality": "normal",
     "bound": False, "acquired_at": "2026-08-18T09:50"},
    {"item_id": "potion_hp", "name": "疗伤药", "count": 5, "quality": "normal",
     "bound": False, "acquired_at": "2026-08-18T10:00"},
]

_ITEMS = {
    "potion_hp": {"id": "potion_hp", "name": "疗伤药", "icon": "✚"},
    "iron_sword": {"id": "iron_sword", "name": "铁剑", "icon": "⚒"},
    "quest_letter": {"id": "quest_letter", "name": "任务信物", "icon": "✉"},
    "iron_ore": {"id": "iron_ore", "name": "铁矿", "icon": "◈"},
    "cloth": {"id": "cloth", "name": "粗布", "icon": ""},
}

_SKILLS = {
    "attack": {"id": "attack", "name": "攻击", "type": "basic", "mp_cost": 0,
               "desc": "对目标发起普通攻击"},
    "fireball": {"id": "fireball", "name": "火球术", "type": "active", "mp_cost": 12,
                 "desc": "对目标造成火焰伤害", "chain_refs": ["chain_fb"]},
    "meteor": {"id": "meteor", "name": "陨星落", "type": "active", "mp_cost": 30,
               "desc": "跃空重击倒地目标"},
    "heavy_smash": {"id": "heavy_smash", "name": "重击", "type": "active", "mp_cost": 8,
                    "desc": "重击地面目标", "chain_refs": ["chain_heavy"]},
    "battle_qi": {"id": "battle_qi", "name": "战意", "type": "passive", "mp_cost": 0,
                  "desc": "每回合回复少量 HP"},
    "counter": {"id": "counter", "name": "反击", "type": "trigger", "mp_cost": 0,
                "desc": "受击时反击"},
    "mage_only": {"id": "mage_only", "name": "奥术弹", "type": "active", "mp_cost": 10,
                  "desc": "法师专属", "job_restrict": ["mage"]},
}

_SKILL_CHAINS = {
    "chain_fb": {"id": "chain_fb", "steps": [{"from": "fireball", "to": "meteor"}]},
    "chain_heavy": {"id": "chain_heavy", "steps": [{"from": "heavy_smash", "to": "meteor"}]},
}

_EQUIPMENT = {
    "weapon": {"item_id": "iron_sword", "name": "铁剑", "slot_level": 3},
    "armor_body": {"item_id": "chain_mail", "name": "锁子甲", "slot_level": 0},
}


class FakeEquipEngine:
    """core/equipment.py 契约替身（equip_wear / equip_remove；装备栏渲染纯函数不依赖引擎）。"""

    def __init__(self, messages=None):
        self.messages = messages or {}

    def equip_wear(self, index, ctx):
        msg = self.messages.get("wear")
        if msg is not None:
            return {"ok": True, "message": msg}
        return {"ok": True, "message": f"✅ 已装备：背包第 {index} 件"}

    def equip_remove(self, slot_id, ctx):
        msg = self.messages.get("remove")
        if msg is not None:
            return {"ok": True, "message": msg}
        return {"ok": True, "message": f"✅ 已卸下：{slot_id}"}


def make_ctx(**over):
    """全字段玩家基础 ctx（每场景新造避免互污染；defaults 对齐各渲染函数消费契约）。"""
    base = {
        "name": "阿伟",
        "level": 3,
        "exp": 320,
        "job_id": "warrior",
        "job_name": "战士",
        "hp": 30,
        "mp": 8,
        "exp_next": 1000,
        "registered": True,
        "is_gm": False,
        "stats": {k: {"name": v} for k, v in _STAT_NAMES.items()},
        "attr_layers": {
            "base": dict(_BASE),
            "bonus": {"flat": {"str": 5}, "pct": {"str": 10}},
            "temp": {"pct": {"str": 20}, "flat": {"str": 3}},
        },
        "items": {k: dict(v) for k, v in _ITEMS.items()},
        "inventory": [dict(r) for r in _INVENTORY],
        "equipment": {k: dict(v) for k, v in _EQUIPMENT.items()},
        "skills": {k: dict(v) for k, v in _SKILLS.items()},
        "skill_chains": {k: dict(v) for k, v in _SKILL_CHAINS.items()},
        "jobs": {"warrior": {"name": "战士"}, "mage": {"name": "法师"}},
        "settings": {},
        "equip_engine": FakeEquipEngine(),
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    """parse_command 封装（parsers.DEFAULT_WHITELIST 已含 角色/背包/装备/技能/帮助）。"""
    return parse_command(raw)


# ---------------------------------------------------------------------------
# /角色：玩家属性面板（LV 行固定头部 + 属性三层结构 + 5 条/页 + TPL-08 + 裁决②）
# ---------------------------------------------------------------------------

def test_view_noarg_page1():
    """/角色 → LV 行固定头部 + 简洁属性前 5 条（不显示白值/加成/临时三层，2026-08-27 用户拍板）。"""
    out = cmd_view(parse("/角色"), make_ctx())
    lines = out.splitlines()
    assert lines[0] == "【角色】Lv3.阿伟（战士） ｜ 经验 320/1000"
    # 资源型：当前/上限
    assert "【生命】30/100" in out
    assert "【魔力】8/30" in out
    # 简洁版：只显最终值，无三层标注
    assert "【力量】29" in out
    assert "【智力】15" in out
    assert "【体质】10" in out
    assert "白值" not in out and "加成" not in out and "临时" not in out   # 简洁版不显示三层
    assert "当前页：1/2" in out
    # 第 2 页条目不在页 1
    assert "幸运" not in out


def test_view_detail_three_layers():
    """/角色详细 → 完整三层明细（白值/加成/临时，2026-08-27 用户拍板 /角色详细 才显示）。"""
    out = cmd_view_detail(parse("/角色详细"), make_ctx())
    assert "【力量】29（白值 15 ｜ 加成 +5·+10% ｜ 临时 +3·+20%）" in out
    assert "【生命】30/100（白值 100 ｜ 加成 0 ｜ 临时 0）" in out
    assert "当前页：1/2" in out


def test_view_page2():
    """/角色 2 → 第 2 页（精神/专注/敏捷/幸运）+ 页脚。"""
    out = cmd_view(parse("/角色 2"), make_ctx())
    assert "【精神】10" in out
    assert "【专注】10" in out
    assert "【敏捷】10" in out
    assert "【幸运】10" in out
    assert "当前页：2/2" in out


def test_view_clamp_last_page():
    """裁决②：/角色 9 超总页数 → 夹取最后一页 + （已到最后一页）。"""
    out = cmd_view(parse("/角色 9"), make_ctx())
    assert "【幸运】10" in out
    assert "（已到最后一页）" in out
    assert "当前页：2/2" in out


@pytest.mark.parametrize("raw", ["/角色 0", "/角色 -1", "/角色 abc", "/角色 1 2"])
def test_view_invalid_tpl12(raw):
    """裁决② + 3d §5.1：0/负数/非数字/超参 → TPL-12。"""
    out = cmd_view(parse(raw), make_ctx())
    assert out == f"❌ 指令不正确：{raw}。输入 /帮助 查看可用指令。"


def test_view_noarg_equiv_page1():
    """/角色 与 /角色 1 输出一致。"""
    assert cmd_view(parse("/角色"), make_ctx()) == cmd_view(parse("/角色 1"), make_ctx())


def test_view_max_level_header():
    """/角色 满级头：Lv≥max_level → 【已满级】。"""
    out = cmd_view(parse("/角色"), make_ctx(level=45, max_level=45, exp=99999))
    assert "【角色】Lv45.阿伟（战士） ｜ 【已满级】" in out.splitlines()[0]


def test_attr_line_pure():
    """attr_line 纯函数：三层结构行（resource 当前/上限 / combat 单值）。"""
    attrs = bc._to_attributes(make_ctx())
    assert attr_line("str", "力量", 29, attrs) == "【力量】29"                       # 默认简洁版
    assert attr_line("hp", "生命", 100, attrs, current=30) == "【生命】30/100"
    assert attr_line("str", "力量", 29, attrs, detail=True) == "【力量】29（白值 15 ｜ 加成 +5·+10% ｜ 临时 +3·+20%）"
    assert attr_line("hp", "生命", 100, attrs, current=30, detail=True) == "【生命】30/100（白值 100 ｜ 加成 0 ｜ 临时 0）"


# ---------------------------------------------------------------------------
# /背包：物品列表（RUL-19 行格式 + acquired_at 倒序 + 5 条/页 + TPL-08 + 裁决②）
# ---------------------------------------------------------------------------

def test_bag_page1_rows_and_footer():
    """/背包 → 第 1 页 5 行（acquired_at 倒序）+ 行格式（图标/×数量/品质/绑定）+ TPL-08 页脚。"""
    out = cmd_bag(parse("/背包"), make_ctx())
    assert out.splitlines()[0] == "1.[疗伤药]×5"          # 10:00 最新在前；[名称]×数量（用户模板）
    assert "2.[粗布]×1" in out                                # ×1 恒显示（用户模板）
    assert "3.[铁矿]×20" in out                               # ×数量（icon 剥离，方括号）
    assert "4.[任务信物]×1（绑定）" in out                    # 绑定标签
    assert "5.[铁剑]×1（精良）" in out                        # 品质（非 normal 标注）
    assert "当前页：1/2(全部)" in out                         # 页数放尾部+类型词（用户模板）
    assert "Tip:发送'使用+物品名'即可使用物品" in out


def test_bag_page2():
    """/背包 2 → 第 2 页（最早获得的疗伤药 ×10）。"""
    out = cmd_bag(parse("/背包 2"), make_ctx())
    assert "6.[疗伤药]×10" in out
    assert "当前页：2/2(全部)" in out


def test_bag_clamp_last_page():
    """裁决②：/背包 9 超总页数 → 夹取最后一页 + （已到最后一页）。"""
    out = cmd_bag(parse("/背包 9"), make_ctx())
    assert "6.[疗伤药]×10" in out
    assert "（已到最后一页）" in out


@pytest.mark.parametrize("raw", ["/背包 0", "/背包 -3", "/背包 abc", "/背包 1 2"])
def test_bag_invalid_tpl12(raw):
    """裁决②：0/负数/非数字/超参 → TPL-12。"""
    out = cmd_bag(parse(raw), make_ctx())
    assert out == f"❌ 指令不正确：{raw}。输入 /帮助 查看可用指令。"


def test_bag_empty():
    """/背包 空背包 → ❌ 背包空空如也（4f §3.4）。"""
    assert cmd_bag(parse("/背包"), make_ctx(inventory=[])) == TPL_EMPTY_BAG


def test_bag_single_page_no_footer():
    """/背包 ≤5 条 → 单页无页脚（3d D-02）。"""
    out = cmd_bag(parse("/背包"), make_ctx(inventory=_INVENTORY[:3]))
    assert "当前页：1/1(全部)" in out                     # 单页也显示当前页+类型词（用户模板）
    # acquired_at 倒序：09:40 信物 → 09:35 铁剑 → 09:30 疗伤药
    assert out.splitlines()[-1] == "Tip:发送'使用+物品名'即可使用物品"


def test_bag_iteminstance_dataclass_support():
    """/背包 兼容 data.item.ItemInstance dataclass 行（无 acquired_at → 保持存储序）。"""
    from qbot_rpg.data.item import ItemInstance
    inv = (
        ItemInstance(item_id="potion_hp", name="疗伤药", count=3, quality="normal", bound=False),
        ItemInstance(item_id="iron_sword", name="铁剑", count=1, quality="fine", bound=True),
    )
    out = cmd_bag(parse("/背包"), make_ctx(inventory=list(inv)))
    assert "1.[疗伤药]×3" in out
    assert "2.[铁剑]×1（精良）（绑定）" in out


def test_bag_line_pure():
    """bag_line 纯函数：用户自定义模板 `{序号}.[{名称}]×{数量}` 行格式边界。"""
    ctx = make_ctx()
    assert bag_line(1, {"item_id": "a", "name": "药", "count": 10, "quality": "normal", "bound": False}, ctx) == "1.[药]×10"
    assert bag_line(2, {"item_id": "b", "name": "剑", "count": 1, "quality": "epic", "bound": True}, ctx) == "2.[剑]×1（史诗）（绑定）"


# ---------------------------------------------------------------------------
# /装备：装备栏（5 条/页 + 空槽 + TPL-08 + 裁决②）+ 切换（穿/卸）
# ---------------------------------------------------------------------------

def test_equip_view_page1():
    """/装备 → 装备栏第 1 页（武器+五部位；空槽（空））+ TPL-08 页脚。"""
    out = cmd_equip(parse("/装备"), make_ctx())
    lines = out.splitlines()
    assert lines[0] == "【装备】Lv3.阿伟（战士）"
    assert "1. 武器：铁剑 +3" in out      # 强化等级 +3
    assert "2. 头部：（空）" in out
    assert "3. 身体：锁子甲" in out       # 无强化不显示 +0
    assert "4. 手部：（空）" in out
    assert "5. 腿部：（空）" in out
    assert "当前页：1/2" in out


def test_equip_view_page2():
    """/装备 2 → 第 2 页（脚部空槽）。"""
    out = cmd_equip(parse("/装备 2"), make_ctx())
    assert "6. 脚部：（空）" in out
    assert "当前页：2/2" in out


def test_equip_view_clamp():
    """裁决②：/装备 9 超总页数 → 夹取最后一页 + （已到最后一页）。"""
    out = cmd_equip(parse("/装备 9"), make_ctx())
    assert "6. 脚部：（空）" in out
    assert "（已到最后一页）" in out


@pytest.mark.parametrize("raw", ["/装备 0", "/装备 abc", "/装备 1 2"])
def test_equip_invalid_page_tpl12(raw):
    """裁决②：0/负数/非数字/超参 → TPL-12。"""
    out = cmd_equip(parse(raw), make_ctx())
    assert out.startswith("❌ 指令不正确：")


def test_equip_wear():
    """/装备 穿 3 → 引擎 equip_wear 消息透传（切换语义）。"""
    out = cmd_equip(parse("/装备 穿 3"), make_ctx())
    assert out == "✅ 已装备：背包第 3 件"


def test_equip_wear_compact():
    """/装备穿3（紧凑）→ 解析器 args[0]="穿3" → 走 TPL-12（紧凑子词+序号需空格）。"""
    # 注：解析器紧凑形态为「装备穿3」→ args=["穿3"]，本层不识别 → TPL-12（显式子词规范）
    out = cmd_equip(parse("/装备穿3"), make_ctx())
    assert out.startswith("❌ 指令不正确：")


@pytest.mark.parametrize("raw", ["/装备 穿", "/装备 穿 abc", "/装备 穿 0"])
def test_equip_wear_invalid(raw):
    """/装备 穿 缺序号/非数字/0 → TPL-12。"""
    out = cmd_equip(parse(raw), make_ctx())
    assert out.startswith("❌ 指令不正确：")


def test_equip_remove_by_id():
    """/装备 卸 weapon → 槽位 id 解析 → 引擎 equip_remove 消息透传。"""
    out = cmd_equip(parse("/装备 卸 weapon"), make_ctx())
    assert out == "✅ 已卸下：weapon"


def test_equip_remove_by_chinese_name():
    """/装备 卸 武器 → 中文名解析 → slot_id。"""
    out = cmd_equip(parse("/装备 卸 武器"), make_ctx())
    assert out == "✅ 已卸下：weapon"


def test_equip_remove_by_seq():
    """/装备 卸 1 → 序号解析（第 1 槽 = weapon）。"""
    out = cmd_equip(parse("/装备 卸 1"), make_ctx())
    assert out == "✅ 已卸下：weapon"


def test_equip_remove_no_slot_value_domain():
    """/装备 卸 不存在 → 「❌ 没有这个装备槽位」（值域问题，不走 TPL-12）。"""
    out = cmd_equip(parse("/装备 卸 不存在"), make_ctx())
    assert out == TPL_NO_SLOT
    assert "输入 /帮助" not in out


def test_equip_remove_missing_arg():
    """/装备 卸（缺槽位）→ TPL-12。"""
    out = cmd_equip(parse("/装备 卸"), make_ctx())
    assert out.startswith("❌ 指令不正确：")


def test_equip_engine_injected_message():
    """/装备 穿 2 引擎自定义消息透传（装配层注入替身）。"""
    eng = FakeEquipEngine(messages={"wear": "✅ 已切换：铁剑"})
    out = cmd_equip(parse("/装备 穿 2"), make_ctx(equip_engine=eng))
    assert out == "✅ 已切换：铁剑"


def test_equip_engine_missing_raises_wiring_pending(monkeypatch):
    """【待接线】防御：装备引擎缺失（core.equipment 不可导入 + 未注入）→ RuntimeError 显式标注。"""
    def boom(name):
        raise ImportError(f"no module {name}")
    monkeypatch.setattr(bc.importlib, "import_module", boom)
    with pytest.raises(RuntimeError) as ei:
        cmd_equip(parse("/装备 穿 1"), make_ctx(equip_engine=None))
    assert "【待接线】" in str(ei.value)
    assert "core/equipment.py" in str(ei.value)


def test_resolve_equip_slot():
    """resolve_equip_slot：id/中文名/序号 → slot_id；找不到 → None。"""
    ctx = make_ctx()
    assert resolve_equip_slot(ctx, "weapon") == "weapon"
    assert resolve_equip_slot(ctx, "武器") == "weapon"
    assert resolve_equip_slot(ctx, "1") == "weapon"
    assert resolve_equip_slot(ctx, "6") == "armor_foot"
    assert resolve_equip_slot(ctx, "不存在") is None
    assert resolve_equip_slot(ctx, "99") is None
    assert resolve_equip_slot(ctx, None) is None


def test_equip_line_pure():
    """equip_line 纯函数：空槽/装备+强化等级。"""
    ctx = make_ctx()
    assert equip_line(1, "weapon", {"item_id": "sw", "name": "铁剑", "slot_level": 3}, ctx) == "1. 武器：铁剑 +3"
    assert equip_line(2, "armor_head", None, ctx) == "2. 头部：（空）"


# ---------------------------------------------------------------------------
# /技能：技能列表（LV 行固定头部 + 类型/MP/描述 + 派生指向 + 职业过滤）
# ---------------------------------------------------------------------------

def test_skill_page1():
    """/技能 → LV 行固定头部 + 技能行（类型/MP/描述/派生指向）+ 5 条/页 + TPL-08。"""
    out = cmd_skill(parse("/技能"), make_ctx())
    lines = out.splitlines()
    assert lines[0] == "【技能】Lv3.阿伟（战士）｜ 技能 6 项"
    assert "1. 攻击（普攻） ｜ 对目标发起普通攻击" in out            # basic 固定第 1 位；MP 0 不显示
    assert "2. 火球术（主动） 12 MP ｜ 对目标造成火焰伤害 ｜ 可派生成：陨星落" in out
    assert "3. 重击（主动） 8 MP ｜ 重击地面目标 ｜ 可派生成：陨星落" in out
    assert "4. 陨星落（主动） 30 MP ｜ 跃空重击倒地目标" in out        # 无派生链 → 无指向
    assert "5. 战意（被动） ｜ 每回合回复少量 HP" in out
    assert "当前页：1/2" in out


def test_skill_page2():
    """/技能 2 → 第 2 页（反击·触发）。"""
    out = cmd_skill(parse("/技能 2"), make_ctx())
    assert "6. 反击（触发） ｜ 受击时反击" in out
    assert "当前页：2/2" in out


def test_skill_job_filter():
    """/技能 职业过滤：job_restrict=['mage'] 的技能对战士不可见（技能 6 项，无 奥术弹）。"""
    out = cmd_skill(parse("/技能"), make_ctx())
    assert "奥术弹" not in out
    assert "技能 6 项" in out
    # 法师可见 奥术弹（技能 7 项：basic/active×4/被动/触发/法师专属）
    out_mage = cmd_skill(parse("/技能"), make_ctx(job_id="mage", job_name="法师"))
    assert "奥术弹（主动） 10 MP ｜ 法师专属" in out_mage
    assert "技能 7 项" in out_mage


def test_skill_derived_names_pure():
    """skill_line 派生指向：chain_refs → steps[].to 技能名（可派生成：XX）。"""
    ctx = make_ctx()
    assert "可派生成：陨星落" in skill_line(2, "fireball", ctx)
    assert "可派生成：" not in skill_line(4, "meteor", ctx)  # 无 chain_refs


def test_skill_rows_order():
    """skill_rows：basic 固定第 1 位 → active → passive → trigger；职业不可见技能排除。"""
    rows = skill_rows(make_ctx())
    assert rows == ["attack", "fireball", "heavy_smash", "meteor", "battle_qi", "counter"]
    assert "mage_only" not in rows


@pytest.mark.parametrize("raw", ["/技能 0", "/技能 -2", "/技能 abc", "/技能 1 2"])
def test_skill_invalid_tpl12(raw):
    """裁决②：0/负数/非数字/超参 → TPL-12。"""
    out = cmd_skill(parse(raw), make_ctx())
    assert out == f"❌ 指令不正确：{raw}。输入 /帮助 查看可用指令。"


def test_skill_empty():
    """/技能 无技能 → 仅 LV 行固定头部（技能 0 项），无页脚。"""
    out = cmd_skill(parse("/技能"), make_ctx(skills={}))
    assert out == "【技能】Lv3.阿伟（战士）｜ 技能 0 项"


# ---------------------------------------------------------------------------
# /帮助：分组目录（普通 5 组单页 / GM 6 组 2 页）+ 组页 + 注册引导版（B6）
# ---------------------------------------------------------------------------

def test_help_directory_normal():
    """/帮助 → 普通玩家 5 组目录单页（无 GM 组、无页脚）。"""
    out = cmd_help(parse("/帮助"), make_ctx())
    assert "【指令总览】输入 /帮助 组名 查看该组指令" in out
    assert "冒险 —— 角色/背包/装备/位置/进入…（/帮助 冒险）" in out
    assert "战斗 —— 攻击/防御/道具/逃跑/技能（/帮助 战斗）" in out
    assert "快捷 —— 快捷绑定/快捷解绑/快捷列表（/帮助 快捷）" in out
    assert "GM" not in out                 # RUL-25 普通玩家不渲染 GM 组
    assert "输入 /帮助 页码 翻页" not in out  # 5 组单页无页脚


def test_help_directory_gm_two_pages():
    """/帮助 GM → 6 组 2 页（第 1 页 5 组 + TPL-08 页脚；GM 组在第 2 页）。"""
    out = cmd_help(parse("/帮助"), make_ctx(is_gm=True))
    # 工程补白 2：目录页脚归一为 TPL-08（m4 §2.2 固定页脚，4f「共 N 组」表述不采用）
    assert "当前页：1/2" in out
    assert "GM —— 重载/封禁/日志/编辑/设置（/帮助 GM）" not in out  # GM 组在页 2
    out2 = cmd_help(parse("/帮助 2"), make_ctx(is_gm=True))
    assert "GM —— 重载/封禁/日志/编辑/设置（/帮助 GM）" in out2
    assert "当前页：2/2" in out2


def test_help_group_page():
    """/帮助 冒险 → 冒险组指令列表 5 条/页 + TPL-08（页脚指令=帮助 冒险）。"""
    out = cmd_help(parse("/帮助 冒险"), make_ctx())
    assert "【冒险】" in out
    assert "1. 角色 —— 查看角色属性面板" in out
    assert "5. 进入 —— 进入地图" in out
    assert "当前页：1/2" in out


def test_help_group_page2():
    """/帮助 冒险 2 → 第 2 页（休息）。"""
    out = cmd_help(parse("/帮助 冒险 2"), make_ctx())
    assert "6. 休息 —— 休息恢复" in out
    assert "当前页：2/2" in out


def test_help_group_single_page_no_footer():
    """/帮助 战斗（5 条组）→ 单页无页脚。"""
    out = cmd_help(parse("/帮助 战斗"), make_ctx())
    assert "1. 攻击 —— 选择技能攻击目标" in out
    assert "5. 技能 —— 查看技能列表" in out
    assert "输入 /帮助 战斗 页码 翻页" not in out


def test_help_unknown_group_tpl12():
    """/帮助 不存在组 → TPL-12。"""
    out = cmd_help(parse("/帮助 不存在"), make_ctx())
    assert out == "❌ 指令不正确：/帮助 不存在。输入 /帮助 查看可用指令。"


@pytest.mark.parametrize("raw", ["/帮助 0", "/帮助 -1", "/帮助 abc", "/帮助 冒险 0", "/帮助 冒险 abc"])
def test_help_invalid_page_tpl12(raw):
    """裁决②：0/负数/非数字 → TPL-12（目录页/组页一致）。"""
    out = cmd_help(parse(raw), make_ctx())
    assert out.startswith("❌ 指令不正确：")


def test_help_directory_clamp_normal():
    """裁决②：/帮助 2（普通玩家目录 1 页）→ 夹取最后一页 + （已到最后一页）。"""
    out = cmd_help(parse("/帮助 2"), make_ctx())
    assert "冒险 —— 角色/背包/装备/位置/进入…（/帮助 冒险）" in out
    assert "（已到最后一页）" in out


def test_help_unregistered_guide():
    """/帮助 未注册 → 注册引导版（B6 豁免；仅注册/角色/背包引导）。"""
    out = cmd_help(parse("/帮助"), make_ctx(registered=False))
    assert "【新手引导】发 /注册 名字 职业 创建角色" in out
    assert "注册 —— 创建角色（未注册必需）" in out
    assert "角色 —— 查看角色属性面板" in out
    assert "背包 —— 查看背包物品" in out


def test_help_groups_constants():
    """/帮助 分组常量：普通 5 组 + GM 组；GM 组仅在 is_gm 时渲染（B8）。"""
    assert len(HELP_GROUPS) == 5
    names = [g[0] for g in HELP_GROUPS]
    assert names == ["冒险", "战斗", "成长", "制造生活", "快捷"]
    assert bc.GM_HELP_GROUP[0] == "GM"


def test_group_page_line_pure():
    """group_page_line：`{序号}. {指令} —— {说明}`。"""
    assert group_page_line(1, ("角色", "查看角色属性面板")) == "1. 角色 —— 查看角色属性面板"


# ---------------------------------------------------------------------------
# 注册门槛 RUL-08（/帮助 豁免 B6）+ 解析接线 + 装配
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("cmd, raw", [
    (cmd_view, "/角色"), (cmd_bag, "/背包"), (cmd_equip, "/装备"), (cmd_skill, "/技能"),
])
def test_register_gate_rul08(cmd, raw):
    """/角色 /背包 /装备 /技能 未注册 → RUL-08 拦截文案；/帮助 豁免。"""
    out = cmd(parse(raw), make_ctx(registered=False))
    assert out == TPL_REGISTER_GATE
    assert "/帮助" not in out or TPL_REGISTER_GATE in out  # 拦截文案不含 /帮助 引导


def test_help_exempt_gate():
    """/帮助 未注册 → 注册引导版而非 RUL-08 拦截（B6 豁免）。"""
    out = cmd_help(parse("/帮助"), make_ctx(registered=False))
    assert out != TPL_REGISTER_GATE
    assert "注册" in out


def test_parse_command_integration():
    """/角色 /背包 /装备 /技能 /帮助 各形态经 parsers.parse_command 产出结构化字段。"""
    p = parse("/角色 2")
    assert p.command == VIEW_CMD and p.args == ["2"]
    p = parse("/背包")
    assert p.command == BAG_CMD and p.args == []
    p = parse("/装备 穿 3")
    assert p.command == EQUIP_CMD and p.args == ["穿", "3"]
    p = parse("/装备 卸 武器")
    assert p.command == EQUIP_CMD and p.args == ["卸", "武器"]
    p = parse("/技能")
    assert p.command == SKILL_CMD and p.args == []
    p = parse("/帮助 冒险")
    assert p.command == HELP_CMD and p.args == ["冒险"]


def test_subword_constants():
    """子指令词常量（穿/卸）。"""
    assert SUB_WEAR == "穿" and SUB_REMOVE == "卸"


def test_register_basic_commands():
    """批次7 装配入口：注册 角色/背包/装备/技能/帮助 五条 CommandSpec（可快捷白名单）。"""
    router = Router()
    register_basic_commands(router, make_context=lambda p: make_ctx())
    for name in (VIEW_CMD, BAG_CMD, EQUIP_CMD, SKILL_CMD, HELP_CMD):
        assert router.has(name)
        assert router.get(name).whitelisted


def test_register_without_make_context_raises():
    """【待接线】无 make_context 时 handler 调用抛 RuntimeError（装配未注入的显式错误）。"""
    router = Router()
    register_basic_commands(router)
    with pytest.raises(RuntimeError):
        router.get(VIEW_CMD).handler(parse("/角色"))


def test_router_parse_integration():
    """/角色 经 parse_command + register 后 handler 可执行（完整链路）。"""
    router = Router()
    register_basic_commands(router, make_context=lambda p: make_ctx())
    out = router.get(VIEW_CMD).handler(parse("/角色"))
    assert out.startswith("【角色】Lv3.阿伟（战士）")


# ---------------------------------------------------------------------------
# 横切：页脚 TPL-08 逐字 / 无装饰 emoji
# ---------------------------------------------------------------------------

def test_footer_tpl08_exact():
    """/角色 /装备 /技能 /帮助 组页 页脚 TPL-08 逐字（无自造变体）；/背包 走用户自定义模板
    （当前页放尾部 + Tip，2026-08-27 用户拍板，不用 TPL-08 页脚）。"""
    ctx = make_ctx()
    assert "当前页：1/2" in cmd_view(parse("/角色"), ctx)
    assert "当前页：1/2(全部)" in cmd_bag(parse("/背包"), ctx)       # /背包 自定义模板
    assert "Tip:发送'使用+物品名'即可使用物品" in cmd_bag(parse("/背包"), ctx)
    assert "当前页：1/2" in cmd_equip(parse("/装备"), ctx)
    assert "当前页：1/2" in cmd_skill(parse("/技能"), ctx)
    assert "当前页：1/2" in cmd_help(parse("/帮助 冒险"), ctx)


def test_no_decorative_emoji():
    """M5 裁决不用 emoji：命令层渲染输出零装饰 emoji（仅 ✅/❌ 功能性标记 + 排版符号）；
    数据型物品 icon 渲染出口剥离 emoji 字符（保纯文本/自定义符号），输出扫描 0 命中。"""
    ctx = make_ctx()
    outputs = [
        cmd_view(parse("/角色"), ctx),
        cmd_view(parse("/角色 2"), ctx),
        cmd_view(parse("/角色 9"), ctx),
        cmd_bag(parse("/背包"), ctx),
        cmd_bag(parse("/背包 2"), ctx),
        cmd_equip(parse("/装备"), ctx),
        cmd_equip(parse("/装备 穿 3"), ctx),
        cmd_equip(parse("/装备 卸 武器"), ctx),
        cmd_skill(parse("/技能"), ctx),
        cmd_skill(parse("/技能 2"), ctx),
        cmd_help(parse("/帮助"), ctx),
        cmd_help(parse("/帮助 冒险"), ctx),
        cmd_help(parse("/帮助"), make_ctx(registered=False)),
        cmd_help(parse("/帮助 0"), ctx),
        TPL_REGISTER_GATE,
        TPL_EMPTY_BAG,
        TPL_NO_SLOT,
    ]
    for text in outputs:
        for ch in text:
            assert ch not in BANNED_EMOJI, f"命中禁用装饰 emoji：{ch} in {text!r}"


def test_pure_helpers_no_nonebot():
    """纯渲染/工具函数：零 NoneBot import 由 G0 架构门禁覆盖；此处断言导出齐全。"""
    for name in ("attr_line", "bag_line", "equip_line", "skill_line", "group_page_line",
                 "resolve_equip_slot", "parse_page_arg", "view_header", "skill_rows"):
        assert callable(getattr(bc, name)), name
