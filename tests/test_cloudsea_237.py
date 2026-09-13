# -*- coding: utf-8 -*-
"""九期237：cloudsea_state v2 迁移＋GM 十指令 spec＋三级溯源诊断包 测试。"""
import importlib

import pytest


def _mig():
    from qbot_rpg.storage import migrations as mig
    importlib.reload(mig)
    return mig


# ---- v2 迁移 ----

def test_schema_version_is_2():
    mig = _mig()
    assert mig.DB_SCHEMA_VERSION == 2


def test_migration_steps_chain_complete():
    mig = _mig()
    assert mig.MIGRATION_STEPS and mig.MIGRATION_STEPS[0][0] == 1
    assert mig.MIGRATION_STEPS[-1][1] == mig.DB_SCHEMA_VERSION
    assert all(fn is not None for _, _, fn in mig.MIGRATION_STEPS)


def test_state_version_constant():
    from qbot_rpg.core.cloudsea_gm import CLOUDSEA_STATE_VERSION
    assert CLOUDSEA_STATE_VERSION == 2


# ---- GM 十指令 ----

def test_gm_commands_ten():
    from qbot_rpg.core.cloudsea_gm import CLOUDSEA_GM_COMMANDS
    assert len(CLOUDSEA_GM_COMMANDS) == 10
    for name, spec in CLOUDSEA_GM_COMMANDS.items():
        assert name.startswith("cs")
        assert {"args", "perm", "desc"} <= set(spec)
    assert "cs诊断" in CLOUDSEA_GM_COMMANDS and "cs重载内容" in CLOUDSEA_GM_COMMANDS


# ---- 三级溯源诊断包 ----

def test_diagnostic_pack_levels():
    from qbot_rpg.core.cloudsea_gm import diagnostic_pack
    kw = dict(overview={"players": 3}, player_detail={"qid": "a"}, raw={"dump": 1})
    l1 = diagnostic_pack(1, **kw)
    assert l1["level"] == 1 and "player_detail" not in l1 and "raw" not in l1
    l2 = diagnostic_pack(2, **kw)
    assert l2["player_detail"] == {"qid": "a"} and "raw" not in l2
    l3 = diagnostic_pack(3, **kw)
    assert l3["raw"] == {"dump": 1}


def test_diagnostic_pack_level_clamped():
    from qbot_rpg.core.cloudsea_gm import diagnostic_pack
    assert diagnostic_pack(9)["level"] == 3
    assert diagnostic_pack(0)["level"] == 1
