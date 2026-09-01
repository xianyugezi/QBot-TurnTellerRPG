"""成就指令壳单测（tests/unit/test_achievement_commands.py · M11 批1 路1C）。

覆盖细化_4c 契约 TC-14/15/17 + TC-16 渲染侧，对齐 docs/m11_成就摸底.md §四 承载表。
"""
from qbot_rpg.commands.achievement_commands import (
    cmd_achievement_info,
    cmd_achievements,
    cmd_title,
    register_achievement_commands,
)


# ---------------------------------------------------------------------------
# 测试夹具（桩 ctx：模拟引擎已注入 achievement_state/achievements/titles）
# ---------------------------------------------------------------------------
def _ctx(entries: list, unlocked: dict | None = None, title_state: dict | None = None,
         registered: bool = True, **extra) -> dict:
    """指令壳 ctx：achievements list + achievement_state + titles 注册表。"""
    ctx = {
        "registered": registered,
        "achievements": {e["id"]: dict(e) for e in entries},
        "achievement_state": {
            "unlocked": unlocked or {},
            "repeat_count": {},
        },
        "titles": {"t_collector": {"name": "收藏家"}, "contest_champion": {"name": "冠军"}},
        "player": {
            "title_state": title_state or {"owned": ["t_collector"], "equipped": "t_collector"},
        },
    }
    ctx.update(extra)
    return ctx


def _entries() -> list:
    return [
        {"id": "ach_1", "name": "成就一", "desc": "描述一",
         "conditions": [{"var": "level", "op": "ge", "value": 5}]},
        {"id": "ach_2", "name": "成就二", "desc": "描述二",
         "conditions": [{"var": "level", "op": "ge", "value": 10}]},
        {"id": "ach_hidden", "name": "万家灯火", "desc": "隐藏",
         "conditions": [{"var": "[事件:神鱼支线完成]", "op": "ge", "value": 8}],
         "hidden": {"mode": "locked", "reveal_text": "灯火即神鱼。"}},
        {"id": "ach_hide", "name": "完全隐藏", "desc": "hide",
         "conditions": [{"var": "level", "op": "ge", "value": 99}],
         "hidden": {"mode": "hide"}},
    ]


class _P:
    """假 ParsedCommand（args 元组）。"""

    def __init__(self, *args: str):
        self.args = tuple(args)
        self.error = None
        self.fragment = ""


# ---------------------------------------------------------------------------
# TC-14 locked 锁定行
# ---------------------------------------------------------------------------
def test_tc14_locked_list():
    """locked 未达成：列表「？？？」锁定行，不渲染明文。"""
    ctx = _ctx(_entries())
    out = cmd_achievements(_P(), ctx)
    assert "？？？" in out  # 锁定行占位
    assert "万家灯火" not in out  # 不渲染明文
    assert "成就一" in out  # 普通成就正常显示


def test_tc14_locked_info():
    """/成就信息 <N> 锁定态只显「？？？」不渲染明文。"""
    ctx = _ctx(_entries())
    # 隐藏成就在第 3 位（未达成按配置序）
    out_info = cmd_achievement_info(_P("3"), ctx)
    assert "？？？" in out_info
    assert "万家灯火" not in out_info


# ---------------------------------------------------------------------------
# TC-15 hide 完全隐藏 + /秘密 不注册
# ---------------------------------------------------------------------------
def test_tc15_hide_list():
    """hide 未达成：列表完全隐藏不占序号（引擎 list_achievements 过滤 + 壳消费）。"""
    ctx = _ctx(_entries())
    out = cmd_achievements(_P(), ctx)
    assert "完全隐藏" not in out  # hide 条目不出现
    assert "成就一" in out
    assert "成就二" in out
    assert "？？？" in out  # locked 隐藏仍占位


def test_tc15_no_secret_command():
    """/秘密 不注册（白名单无此词）。"""
    from qbot_rpg.commands.parsers import DEFAULT_WHITELIST
    assert "秘密" not in DEFAULT_WHITELIST


# ---------------------------------------------------------------------------
# TC-16 渲染侧（成就列表 header + 状态标记）
# ---------------------------------------------------------------------------
def test_tc16_render_header_state():
    """成就列表 header 含分页/进度 + 达成状态标记。"""
    ctx = _ctx(_entries(), unlocked={"ach_1": "2026-09-01"})
    out = cmd_achievements(_P(), ctx)
    assert "已达成" in out or "✅" in out
    assert "【成就】" in out


# ---------------------------------------------------------------------------
# TC-17 分页（5 条/页）
# ---------------------------------------------------------------------------
def test_tc17_page():
    """分页：超 5 条翻页；页码解析。"""
    entries = [
        {"id": f"ach_{i}", "name": f"成就{i}", "conditions": []} for i in range(1, 7)
    ]
    ctx = _ctx(entries)
    out1 = cmd_achievements(_P(), ctx)
    assert "成就1" in out1
    assert "成就6" not in out1  # 第 1 页只 5 条
    out2 = cmd_achievements(_P("2"), ctx)
    assert "成就6" in out2


# ---------------------------------------------------------------------------
# /称号
# ---------------------------------------------------------------------------
def test_title_view():
    """/称号 查看：当前佩戴 + 已拥有列表。"""
    ctx = _ctx([], title_state={"owned": ["t_collector"], "equipped": "t_collector"})
    out = cmd_title(_P(), ctx)
    assert "t_collector" in out
    assert "收藏家" in out or "当前" in out


def test_title_equip():
    """/称号 佩戴 <N>：按序号佩戴。"""
    ctx = _ctx([], title_state={"owned": ["t_collector", "contest_champion"], "equipped": None})
    out = cmd_title(_P("佩戴", "2"), ctx)
    assert "contest_champion" in out


def test_title_empty():
    """无称号 → 空态。"""
    ctx = _ctx([], title_state={"owned": [], "equipped": None})
    out = cmd_title(_P(), ctx)
    assert "暂无称号" in out


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------
def test_register():
    """注册函数返回 router（三指令）。"""
    class FakeRouter:
        def __init__(self):
            self.specs = []

        def register(self, spec):
            self.specs.append(spec)

    r = FakeRouter()
    out = register_achievement_commands(r)
    assert out is r
    names = [s.name for s in r.specs]
    assert "成就" in names
    assert "成就信息" in names
    assert "称号" in names
