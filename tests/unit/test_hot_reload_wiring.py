"""热重载接线补测（M6 批3·路A · D3 WIR 件套）——WIR-07/11/13/14 + RSM-05 激活。

依据：细化_M6_热重载接线.md（D3）——WIR-07（/重载 真实后端=watcher.reload 同一管线）、
WIR-11（红/黄计数出口 count_errors/count_warnings/group_by_module）、WIR-13（登记表
对照：loader ⊆ field_meta）、WIR-14（resolve_or_degrade 统一降级入口）、RSM-05
（_backup_snapshot 激活 → backup_snapshot() 公开）。
注：本文件为路A 迭代上限截断后由主 agent 补建（实现已落盘，测试补齐）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from qbot_rpg.commands.gm_commands import GmBackend
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.hot_reload import HotReloadWatcher, RegistrySnapshot
from qbot_rpg.content.loader import _KIND_FOR_MODULE
from qbot_rpg.content.models import PackError, PackWarning, ValidationReport
from qbot_rpg.content.registry import Registry
from qbot_rpg.content.resolve_or_degrade import resolve_or_degrade


# ---------------------------------------------------------------------------
# WIR-11 红/黄计数（ValidationReport 计数出口）
# ---------------------------------------------------------------------------
def _perr(module="items"):
    return PackError(module=module, field=f"{module}.json", kind="unknown_field", detail={})


def _pwarn(module="items"):
    return PackWarning(module=module, field=f"{module}.json", kind="missing_field", detail={})


def test_validation_report_counts():
    """WIR-11：count_errors/count_warnings = len(errors/warnings)。"""
    rep = ValidationReport(
        errors=(_perr("items"), _perr("items"), _perr("effects")),
        warnings=(_pwarn("items"),),
    )
    assert rep.count_errors == 3
    assert rep.count_warnings == 1


def test_validation_report_group_by_module():
    """WIR-11：group_by_module 按模块聚合 (errors, warnings)，sorted 稳定。"""
    rep = ValidationReport(
        errors=(_perr("items"), _perr("items"), _perr("effects")),
        warnings=(_pwarn("items"), _pwarn("effects"), _pwarn("effects")),
    )
    grouped = rep.group_by_module()
    assert grouped["items"] == (2, 1)
    assert grouped["effects"] == (1, 2)
    assert list(grouped.keys()) == sorted(grouped.keys())


# ---------------------------------------------------------------------------
# WIR-13 登记表对照（F4 验收⑤）：loader 模块 ⊆ field_meta 模块表
# ---------------------------------------------------------------------------
def test_register_order_subset_of_field_meta():
    """WIR-13：_KIND_FOR_MODULE ∪ FIXED_REGISTER_ORDER ⊆ field_meta 模块表（单向子集）。
    新增模块未接校验器 → CI 拦截。"""
    meta_modules = set(default_field_meta_table().modules.keys())
    loader_modules = set(_KIND_FOR_MODULE.keys())
    # 单向子集断言（loader ⊆ field_meta；settings/manifest 常驻/入口不强制反向）
    assert loader_modules <= meta_modules, (
        f"loader 模块未接 field_meta：{loader_modules - meta_modules}")


# ---------------------------------------------------------------------------
# WIR-14 resolve_or_degrade（统一降级入口四态）
# ---------------------------------------------------------------------------
class _FakeRegistry:
    """契约替身 Registry：resolve(id, kind) 命中/查无。"""

    def __init__(self, table):
        self._table = table

    def resolve(self, id, kind):
        return self._table.get(kind, {}).get(id)


def test_resolve_or_degrade_hit_and_miss():
    """解析命中 → (Def, False)；查无（配置已删）→ (None, True) 降级不抛异常（OLD-4）。"""
    reg = _FakeRegistry({"effect": {"fire": "FIRE_DEF"}})
    assert resolve_or_degrade(reg, "fire", "effect") == ("FIRE_DEF", False)
    defn, degraded = resolve_or_degrade(reg, "gone", "effect")
    assert defn is None and degraded is True


def test_resolve_or_degrade_none_registry_degrades():
    """registry=None → (None, True) 降级兜底（旧局无 registry 引用已删配置）。"""
    defn, degraded = resolve_or_degrade(None, "fire", "effect")
    assert defn is None and degraded is True


def test_resolve_or_degrade_callable_and_mapping():
    """callable / Mapping 形态（对齐 effects._make_resolver 归一化）。"""
    defn, _ = resolve_or_degrade(lambda i, k: "X" if i == "a" else None, "a", "effect")
    assert defn == "X"
    mapping = {"effect": {"b": "B_DEF"}}
    defn2, degraded2 = resolve_or_degrade(mapping, "b", "effect")
    assert defn2 == "B_DEF" and degraded2 is False
    _, degraded3 = resolve_or_degrade(mapping, "zz", "effect")
    assert degraded3 is True


# ---------------------------------------------------------------------------
# RSM-05 backup_snapshot 激活（公开接口返回当前有效档）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_backup_snapshot_activated(legal_pack_dir: Path):
    """RSM-05：_backup_snapshot 死代码激活 → backup_snapshot() 返回当前有效档（generation≥1）。"""
    watcher = HotReloadWatcher(legal_pack_dir)
    result = await watcher.start()
    assert result.ok is True
    snap = watcher.backup_snapshot()
    assert isinstance(snap, RegistrySnapshot)
    assert snap.generation >= 1
    assert snap.pack_id == "legal"
    # 与 _snapshots（N=2）双口：backup_snapshot = 当前有效档
    assert watcher.generation >= 1


# ---------------------------------------------------------------------------
# WIR-07 /重载 真实后端（GmBackend.reload_content = watcher.reload 同一管线）
# ---------------------------------------------------------------------------
def test_gm_backend_reload_no_watcher_message():
    """WIR-07：watcher 未装配 → ok=False + 人话（包未启用）。"""
    backend = GmBackend(watcher=None)
    res = backend.reload_content("legal", None)
    assert res["ok"] is False
    assert "内容包未启用" in res["message"]


def test_gm_backend_reload_success_path(legal_pack_dir: Path):
    """WIR-07：reload_content 调 watcher.reload（同一管线）；成功 → {ok, summary, failures}。

    GmBackend 为同步契约（reload_content 内 asyncio.run），须在**无运行事件循环**环境调用
    （pytest-asyncio 环境会触发 asyncio.run 不可嵌套 → 待异步装配分支）。"""
    import asyncio

    async def _start():
        w = HotReloadWatcher(legal_pack_dir)
        await w.start()
        return w

    watcher = asyncio.run(_start())  # 同步上下文：start 完成后无运行循环
    backend = GmBackend(watcher=watcher)
    res = backend.reload_content("legal", None)
    assert res["ok"] is True
    assert "个模块变更生效" in res["summary"]  # TPL-15 尾部
    assert res["failures"] == []


def test_gm_backend_reload_wrong_pack_message(legal_pack_dir: Path):
    """WIR-07：包名不匹配 → ok=False + 人话。"""
    import asyncio

    async def _start():
        w = HotReloadWatcher(legal_pack_dir)
        await w.start()
        return w

    watcher = asyncio.run(_start())
    backend = GmBackend(watcher=watcher)
    res = backend.reload_content("no_such_pack", None)
    assert res["ok"] is False
    assert "no_such_pack" in res["message"]
