# -*- coding: utf-8 -*-
"""九期批次 231 定向测试：cloudsea_commands 接线（帮/预/局面/挂/撤/数字快捷＋冲突矩阵零撞）。

红线自证：只注册新词面；框架既有 96 词面零触碰（冲突矩阵程序化复扫）；
战斗引擎零交叉 import（handler 纯函数 parsed+ctx→str）。
"""
import io
import os
import re
from types import SimpleNamespace

import pytest

from qbot_rpg.commands import cloudsea_commands as cc


class _Router:
    def __init__(self):
        self.specs = {}

    def register(self, spec):
        self.specs[spec.name] = spec


def _parsed(cmd, args=(), raw=None):
    return SimpleNamespace(command=cmd, args=list(args), raw=raw or f"/{cmd}", error=None)


def _ctx(**kw):
    return dict(kw)


# ---------------------------------------------------------------- 注册与词面


def test_register_all_faces():
    r = _Router()
    cc.register_cloudsea_commands(r)
    expect = {"帮", "预", "局面", "挂", "撤", "1", "2", "3", "4", "绝"}
    assert expect == set(r.specs.keys())
    assert all(s.handler for s in r.specs.values())


def test_no_conflict_with_framework_faces():
    """冲突矩阵程序化复扫：框架既有词面 × 云海新词面零撞（`合成` 复用除外——不注册）。"""
    cmds_dir = os.path.join(os.path.dirname(cc.__file__))
    faces = set()
    for fn in os.listdir(cmds_dir):
        if not fn.endswith(".py") or fn == "cloudsea_commands.py":
            continue
        t = io.open(os.path.join(cmds_dir, fn), encoding="utf-8").read()
        for m in re.finditer(r"^([A-Z_0-9]+)_CMD(?::\s*str)?\s*=\s*[\"']([^\"']+)", t, re.M):
            faces.add(m.group(2))
    mine = {"帮", "预", "局面", "挂", "撤", "1", "2", "3", "4", "绝", "合成"}
    assert not (faces & mine - {"合成"}), faces & mine
    assert "合成" in faces  # 复用而非重注册


def test_register_requires_router():
    with pytest.raises(ValueError):
        cc.register_cloudsea_commands(None)


# ---------------------------------------------------------------- 帮


def test_help_panel_and_lookup():
    panel = cc.cmd_help_cloudsea(_parsed("帮"), _ctx())
    assert "云海猎团 · 速查" in panel and "局面" in panel
    row = cc.cmd_help_cloudsea(_parsed("帮", ["挂"]), _ctx())
    assert "挂" in row
    miss = cc.cmd_help_cloudsea(_parsed("帮", ["无关词"]), _ctx())
    assert "指令不正确" in miss and "发 帮助" in miss  # 免斜杠（M8）＋errors 唯一源文案（作者线）


# ---------------------------------------------------------------- 预


def test_preset_spec_and_lookup():
    out = cc.cmd_preset(_parsed("预"), _ctx())
    assert "预案串" in out and "232" in out
    out2 = cc.cmd_preset(_parsed("预", ["守势一"]), _ctx(
        cloudsea_presets={"守势一": "1 守势 2 调和"}))
    assert "守势一" in out2 and "守势" in out2
    miss = cc.cmd_preset(_parsed("预", ["不存在"]), _ctx())
    assert "未找到" in miss


# ---------------------------------------------------------------- 局面


def test_situation_no_battle():
    out = cc.cmd_situation(_parsed("局面"), _ctx())
    assert "没有进行中的战斗" in out


def test_situation_aggregate():
    snap = {
        "player_hp": 820,
        "enemy": {"hp": 31400, "intent": "🌀 蓄力"},
        "resource_state": {"enemy": {"cs_surge": 14, "cs_stamina": 6}},
    }
    out = cc.cmd_situation(_parsed("局面"), _ctx(battle_snapshot=snap))
    assert "❤️820" in out and "🎯31400" in out and "🌊14" in out and "😮‍💨6" in out
    out2 = cc.cmd_situation(_parsed("局面"), _ctx(battle_snapshot={"empty": 1}))
    assert "234" in out2


# ---------------------------------------------------------------- 挂 N


def test_hang_range_and_write():
    ok = cc.cmd_hang(_parsed("挂", ["3"]), _ctx())
    assert "3 场" in ok
    over = cc.cmd_hang(_parsed("挂", ["11"]), _ctx())
    assert "超域" in over
    bad = cc.cmd_hang(_parsed("挂", ["abc"]), _ctx())
    assert "用法" in bad
    ctx = _ctx()
    cc.cmd_hang(_parsed("挂", ["5"]), ctx)
    assert ctx["cloudsea_delegate_n"] == 5


# ---------------------------------------------------------------- 撤


def test_retreat_two_phase():
    idle = cc.cmd_retreat(_parsed("撤"), _ctx())
    assert "没有进行中的战斗" in idle
    ctx = _ctx(battle_snapshot={"enemy": {"hp": 1}})
    warn = cc.cmd_retreat(_parsed("撤"), ctx)
    assert "确认" in warn and ctx["cloudsea_retreat_pending"] is True
    done = cc.cmd_retreat(_parsed("撤", ["确认"]), ctx)
    assert "撤退成立" in done and ctx["cloudsea_retreat_done"] is True


# ---------------------------------------------------------------- 数字快捷


def test_digit_bindings_echo_and_hook():
    out = cc.cmd_digit(_parsed("1"), _ctx())
    assert "1 → /攻击" in out and "234" in out
    calls = []
    ctx = _ctx(shortcut_exec=lambda t, p, c: calls.append(t) or f"[转发]{t}")
    out2 = cc.cmd_digit(_parsed("绝"), ctx)
    assert calls == ["/绝技"] and "[转发]" in out2


def test_digit_all_registered():
    r = _Router()
    cc.register_cloudsea_commands(r)
    for d in cc.DIGIT_BINDINGS:
        out = r.specs[d].handler(_parsed(d), _ctx())
        assert cc.DIGIT_BINDINGS[d] in out
