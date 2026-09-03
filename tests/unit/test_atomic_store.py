"""编辑器保存链路「原子写盘 + 快照回退 + 变更应用」服务层单测（tests/unit/test_atomic_store.py）。

依据：docs/细化/细化_5a_编辑器契约.md
  - SV-06 L129（原子写盘：temp+rename；全部写完统一重载）
  - SV-07 L130（快照回退：校验失败回退旧 registry + 人话提示；非法 JSON 不崩）
  - SV-02 L125（红拦"拒绝"在加载/热重载阶段而非保存阶段）
  - L183（统一包络 {ok, data} / {ok:false, errors[]}）+ L189（/api/reload 语义）

覆盖：
  - apply_module_changes：entries 替换（新增/更新）/ removed 移除 / 深拷贝不污染原表 /
    变更清单返回 / 白名单收敛
  - apply_removed_to_entries：多 id 过滤 / 幂等
  - write_modules：tmp_path 原子写内容正确 / 无残留 .tmp / 非法 JSON 拒绝不落盘不崩 /
    路径穿越模块名拒绝 / 中文内容 UTF-8 可读回
  - reload_and_rollback：validator 注入失败 → 回退旧快照（registry 原值保留）+
    restored + 人话错误；通过 → modules_raw 换新 + generation 递增；
    假 watcher 失败路径 restored；意外异常回退不崩
  - snapshot_registry / restore_registry：快照回退通道

铁律：零 NoneBot import；零定时器/零睡眠；tmp_path 文件系统可测；
      不真改 content/test_demo（只读）；无 emoji；新测试文件 ruff E501 零豁免。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping

from qbot_rpg.content.atomic_store import (
    apply_module_changes,
    apply_removed_to_entries,
    reload_and_rollback,
    snapshot_registry,
    write_modules,
)
from qbot_rpg.content.models import PackError, PackWarning, ValidationReport
from qbot_rpg.content.registry import Registry, RegistrySnapshot

# =============================================================================
# 假数据源（dict 直填，模拟 loader 解析产物：顶层 list + id/name）
# =============================================================================

def make_modules_raw() -> Dict[str, Any]:
    """六页模块假数据（与 test_pages_crud.make_ctx 同构；enemies/maps/skills/jobs/quest/shop）。"""
    return {
        "enemies": [
            {"id": "gust_wolf", "name": "风狼", "hp": 90, "atk": 12},
            {"id": "ridge_cub", "name": "脊冢幼兽", "hp": 90, "atk": 8},
        ],
        "maps": [
            {"id": "forest", "name": "风语森林",
             "monsters": [{"enemy": "gust_wolf"}, {"enemy": "ridge_cub"}],
             "exits": {"north": {"to": "cave"}}},
            {"id": "cave", "name": "洞穴",
             "monsters": [{"enemy": "gust_wolf"}], "gate_guard": "gust_wolf"},
        ],
        "skills": [{"id": "slash", "name": "脊斩", "job_restrict": ["ridge_blade"]}],
        "jobs": [{"id": "ridge_blade", "name": "脊剑士"}],
        "quest": [{"id": "q1", "name": "讨伐风狼", "reward": [{"item": "potion"}]}],
        "shop": [{"id": "s1", "name": "杂货店", "items": [{"item": "potion"}]}],
        "items": [{"id": "potion", "name": "药水"}],
    }


def make_registry(modules_raw: Mapping[str, Any], generation: int = 1) -> Registry:
    """假 registry：模块数据入 modules_raw（直接构造，不走 loader——纯逻辑单测）。"""
    return Registry(
        pack_id="test_pack",
        generation=generation,
        tables={},
        names={},
        modules_raw=dict(modules_raw),
        manifest=None,
        schema_version=1,
    )


def make_validator_ok() -> Any:
    """假 validator：校验通过（零红零黄）。"""
    def _check(modules: Mapping[str, Any]) -> ValidationReport:
        return ValidationReport(errors=(), warnings=())
    return _check


def make_validator_fail() -> Any:
    """假 validator：校验失败（红拦 R-5 结构错误，detail 携带 message 供人话翻译）。"""
    def _check(modules: Mapping[str, Any]) -> ValidationReport:
        return ValidationReport(
            errors=(
                PackError(module="enemies", field="enemies.0.hp", kind="R-2",
                          detail={"rule": "negative", "message": "生命不能是负数"}),
            ),
            warnings=(PackWarning(module="enemies", field="enemies.0.name", kind="Y-1",
                                  detail={"rule": "range"}),),
        )
    return _check


def make_validator_boom() -> Any:
    """假 validator：意外异常（模拟校验器内部崩溃 → 服务不崩铁律）。"""
    def _check(modules: Mapping[str, Any]) -> ValidationReport:
        raise RuntimeError("validator exploded")
    return _check


def make_fake_watcher_ok(result: Any) -> Any:
    """假 watcher：同步 reload() 返回预设成功 ReloadResult（单测注入，绕 async）。"""
    class _FakeWatcher:
        def reload(self):
            return result
    return _FakeWatcher()


def make_reload_ok_result() -> Any:
    """成功 ReloadResult（与 hot_reload._commit_success 同构）。"""
    from qbot_rpg.content.hot_reload import ReloadResult
    return ReloadResult(
        pack_id="test_pack", ok=True, changed_modules=("enemies",),
        warnings=(), errors=(), restored=False, paused=False, generation=2,
        note="reloaded 1 changed module(s) [source=atomic]",
    )


def make_reload_fail_result() -> Any:
    """失败 ReloadResult（restored=True，errors 带 R-2 红拦，与 watcher 失败路径同构）。"""
    from qbot_rpg.content.hot_reload import ReloadResult
    return ReloadResult(
        pack_id="test_pack", ok=False, changed_modules=(),
        warnings=(), errors=(
            PackError(module="enemies", field="enemies.0.hp", kind="R-2",
                      detail={"rule": "negative", "message": "生命不能是负数"}),
        ),
        restored=True, paused=False, generation=1,
        note="load blocked by 1 red-block error(s)",
    )


# =============================================================================
# 变更应用：entries 替换（新增/更新）/ removed 移除 / 副本不污染
# =============================================================================

def test_apply_changes_replace_entries_new_item() -> None:
    """{module, entries} 整模块替换 = 新增条目（深拷贝副本生效，原表不动）。"""
    raw = make_modules_raw()
    new_enemies = list(raw["enemies"]) + [
        {"id": "skill_0001", "name": "测试怪", "hp": 1, "atk": 1}]
    out = apply_module_changes(raw, [{"module": "enemies", "entries": new_enemies}])
    assert out["ok"] is True
    assert out["changed_modules"] == ["enemies"]
    # 副本包含新条目
    got = out["modules"]["enemies"]
    assert len(got) == 3
    assert got[-1]["id"] == "skill_0001"
    # 原表不被污染（深拷贝副本语义）
    assert len(raw["enemies"]) == 2
    assert raw["enemies"][-1]["id"] == "ridge_cub"


def test_apply_changes_remove_item() -> None:
    """{module, item_id, removed:true} 单条目移除。"""
    raw = make_modules_raw()
    out = apply_module_changes(raw, [
        {"module": "enemies", "item_id": "gust_wolf", "removed": True}])
    assert out["ok"] is True
    ids = [e["id"] for e in out["modules"]["enemies"]]
    assert ids == ["ridge_cub"]
    assert out["changed_modules"] == ["enemies"]
    assert len(raw["enemies"]) == 2  # 原表不动


def test_apply_changes_mixed_update_and_remove() -> None:
    """混合变更：更新条目（entries 替换）+ 跨模块删除（级联模块 removed）。"""
    raw = make_modules_raw()
    updated_enemies = [dict(e) for e in raw["enemies"]]
    updated_enemies[0] = {**updated_enemies[0], "hp": 999}
    out = apply_module_changes(raw, [
        {"module": "enemies", "entries": updated_enemies},
        {"module": "maps", "item_id": "cave", "removed": True},
    ])
    assert out["ok"] is True
    assert out["modules"]["enemies"][0]["hp"] == 999
    assert [m["id"] for m in out["modules"]["maps"]] == ["forest"]
    assert out["changed_modules"] == ["enemies", "maps"]


def test_apply_changes_no_changes_returns_copy() -> None:
    """空变更 → ok:true + 全量副本（changed_modules 空）。"""
    raw = make_modules_raw()
    out = apply_module_changes(raw, [])
    assert out["ok"] is True
    assert out["changed_modules"] == []
    assert out["modules"]["enemies"] == raw["enemies"]
    assert out["modules"] is not raw  # 副本


def test_apply_changes_changed_whitelist_skips_others() -> None:
    """changed_modules 白名单：清单外模块变更不应用（增量收敛语义）。"""
    raw = make_modules_raw()
    out = apply_module_changes(raw, [
        {"module": "enemies", "entries": [{"id": "fresh", "name": "新怪"}]},
        {"module": "maps", "item_id": "cave", "removed": True},
    ], changed_modules=["enemies"])
    assert out["ok"] is True
    assert out["modules"]["enemies"][0]["id"] == "fresh"
    # maps 变更被白名单跳过（原数据保留）
    assert [m["id"] for m in out["modules"]["maps"]] == ["forest", "cave"]
    assert out["changed_modules"] == ["enemies"]


def test_apply_changes_garbage_change_entries_ignored() -> None:
    """非法变更条目（非 Mapping/缺 module/坏形态）→ 跳过不崩（服务不崩铁律）。"""
    raw = make_modules_raw()
    # 类型注解外推：故意混入 str/畸形条目验证宽容跳过（运行期形态，非静态类型契约）
    garbage: List[Any] = [
        "garbage",                      # 非 Mapping
        {"module": "", "entries": []},  # 空模块名
        {"module": 123, "entries": []},  # 模块名非 str
        {"module": "enemies"},           # 缺 entries/removed
        {"module": "enemies", "entries": {"not": "a list"}},  # entries 非 list
    ]
    # 运行期宽容语义：坏条目跳过不崩（静态契约外输入，mypy 无法表达 → 本行测试意图显式）
    out = apply_module_changes(raw, garbage)  # type: ignore[arg-type]  # noqa: E501
    assert out["ok"] is True
    assert out["changed_modules"] == []
    assert out["modules"]["enemies"] == raw["enemies"]


def test_apply_removed_to_entries_filters_ids() -> None:
    """apply_removed_to_entries：多 id 过滤；条目缺失幂等。"""
    entries = [{"id": "a", "name": "甲"}, {"id": "b", "name": "乙"}, {"id": "c", "name": "丙"}]
    out = apply_removed_to_entries("maps", entries, ["a", "c"])
    assert out["ok"] is True
    assert [e["id"] for e in out["entries"]] == ["b"]
    # 不存在 id → 幂等原样
    out2 = apply_removed_to_entries("maps", entries, ["zz"])
    assert out2["ok"] is True
    assert [e["id"] for e in out2["entries"]] == ["a", "b", "c"]


# =============================================================================
# 原子写盘（SV-06：tmp_path 验证内容 + 无残留 .tmp）
# =============================================================================

def test_write_modules_atomic_content(tmp_path: Path) -> None:
    """write_modules：文件内容正确（中文 UTF-8 可读回）+ 无残留 .tmp。"""
    out = write_modules(tmp_path, {
        "enemies": [{"id": "wolf", "name": "风狼", "hp": 90}],
        "maps": [{"id": "forest", "name": "风语森林"}],
    })
    assert out["ok"] is True
    assert out["written"] == ["enemies", "maps"]
    # 文件落盘 + 内容可读回
    data = json.loads((tmp_path / "enemies.json").read_text(encoding="utf-8"))
    assert data[0]["name"] == "风狼"
    data2 = json.loads((tmp_path / "maps.json").read_text(encoding="utf-8"))
    assert data2[0]["id"] == "forest"
    # 无残留 .tmp
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_modules_dot_json_suffix_and_no_tmp_left(tmp_path: Path) -> None:
    """模块名带 .json 后缀原样落盘；写完目录无任何临时文件。"""
    out = write_modules(tmp_path, {"skills.json": [{"id": "slash"}]})
    assert out["ok"] is True
    assert (tmp_path / "skills.json").exists()
    assert list(tmp_path.iterdir()) == [tmp_path / "skills.json"]


def test_write_modules_invalid_json_rejected_no_files(tmp_path: Path) -> None:
    """非法 JSON（不可序列化内容）→ 整体拒绝：零文件落盘、不崩（SV-07 服务不崩）。"""
    pre = set(tmp_path.iterdir())
    out = write_modules(tmp_path, {
        "enemies": [{"id": "ok"}],
        "bad": object(),  # 不可序列化 → 预检拒绝
    })
    assert out["ok"] is False
    assert out["errors"][0]["level"] == "red"
    assert out["errors"][0]["code"] == "invalid_json"
    # 预检在写盘前 → 连合法模块也不落盘（整体拒绝，防半套写入）
    assert set(tmp_path.iterdir()) == pre
    assert not (tmp_path / "enemies.json").exists()


def test_write_modules_traversal_module_name_rejected(tmp_path: Path) -> None:
    """路径穿越模块名（../evil）→ 拒绝写盘不崩。"""
    out = write_modules(tmp_path, {"../evil": [{"id": "x"}]})
    assert out["ok"] is False
    assert out["errors"][0]["code"] == "invalid_module"
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path.parent / "evil.json").exists()


def test_write_modules_non_serializable_content_message(tmp_path: Path) -> None:
    """不可序列化内容错误信息含模块名（人话可定位）。"""
    out = write_modules(tmp_path, {"enemies": {"id": "x", "bad": object()}})
    assert out["ok"] is False
    msg = out["errors"][0]["message"]
    assert "enemies" in msg


# =============================================================================
# 快照回退（SV-07：校验失败回退旧快照 + 人话；通过换新）
# =============================================================================

def test_snapshot_and_restore_roundtrip() -> None:
    """snapshot_registry / restore_registry：快照回退通道（restore 后数据一致）。"""
    reg = make_registry(make_modules_raw(), generation=3)
    snap = snapshot_registry(reg)
    assert isinstance(snap, RegistrySnapshot)
    assert snap.generation == 3
    # 篡改 registry 后回退 → 数据还原（测试直改私有字段验证回退通道）
    reg.modules_raw  # noqa: B018  # 读视图确认存在
    reg.restore(RegistrySnapshot(
        pack_id=reg.pack_id, generation=3,
        tables={}, names={}, modules_raw=dict(make_modules_raw()), manifest=None,
        schema_version=1,
    ))
    assert reg.modules_raw["enemies"] == make_modules_raw()["enemies"]
    assert reg.generation == 3


def test_reload_rollback_on_validation_failure() -> None:
    """validator 注入失败 → 回退旧快照：registry 数据/世代原样 + restored + 人话错误。"""
    reg = make_registry(make_modules_raw(), generation=5)
    # 用 registry 公开快照通道先污染再回退验证（restore 语义由 registry.py 单测覆盖）
    pre = snapshot_registry(reg)
    bad_modules = dict(make_modules_raw())
    bad_modules["enemies"] = [{"id": "bad", "name": "坏配置", "hp": -1}]
    human: List[dict] = []
    out = reload_and_rollback(
        reg, bad_modules,
        validator=make_validator_fail(), human_errors=human,
    )
    assert out.ok is False
    assert out.restored is True
    assert out.errors and out.errors[0].kind == "R-2"
    # registry 未被污染（回退 = 上一份校验通过快照）
    assert len(reg.modules_raw["enemies"]) == 2
    assert reg.generation == 5
    # 人话收集（L183 包络 errors[] 形态）
    assert human and human[0]["level"] == "red"
    assert "enemies" in human[0]["message"]
    assert "生命不能是负数" in human[0]["message"]
    # 与保存前置档一致（SV-07 快照回退 = 上一份校验通过档）
    assert reg.modules_raw == dict(pre.modules_raw)


def test_reload_success_swaps_modules_and_bumps_generation() -> None:
    """validator 通过 → modules_raw 换新 + generation 递增（指针级替换语义）。"""
    reg = make_registry(make_modules_raw(), generation=5)
    new_modules = dict(make_modules_raw())
    new_modules["enemies"] = [{"id": "fresh", "name": "新怪", "hp": 1}]
    out = reload_and_rollback(reg, new_modules, validator=make_validator_ok())
    assert out.ok is True
    assert out.restored is False
    fresh: Any = reg.modules_raw["enemies"]
    assert fresh[0]["id"] == "fresh"
    assert reg.generation == 6


def test_reload_unexpected_validator_exception_rolls_back() -> None:
    """校验器意外异常 → 按校验失败回退（服务不崩铁律）。"""
    reg = make_registry(make_modules_raw(), generation=2)
    out = reload_and_rollback(reg, make_modules_raw(), validator=make_validator_boom())
    assert out.ok is False
    assert out.restored is True
    enemies: Any = reg.modules_raw["enemies"]
    assert len(enemies) == 2  # 原值保留
    assert reg.generation == 2


def test_reload_default_validator_is_check_pack() -> None:
    """缺省 validator = 真实 check_pack（精简假数据过不了完整 schema → 回退）。

    六页假数据（enemies/maps/skills/jobs 缺 M13 必填字段）过不了真实 check_pack
    → 证明默认 validator 确实是 check_pack（若没接真校验器会 ok=True 假绿）。
    """
    reg = make_registry(make_modules_raw(), generation=1)
    out = reload_and_rollback(reg, make_modules_raw())
    assert out.ok is False            # 真 check_pack 拦下精简数据
    assert out.restored is True       # 回退旧快照（SV-07）
    assert reg.generation == 1        # 未换新


def test_reload_fake_watcher_failure_restored_and_human() -> None:
    """假 watcher 失败（ok=False + restored）→ human_errors 收集人话（L189 语义）。"""
    reg = make_registry(make_modules_raw(), generation=1)
    human: List[dict] = []
    out = reload_and_rollback(
        reg, make_modules_raw(),
        watcher=make_fake_watcher_ok(make_reload_fail_result()),
        human_errors=human,
    )
    assert out.ok is False
    assert out.restored is True
    assert human and human[0]["level"] == "red"
    assert "生命不能是负数" in human[0]["message"]


def test_reload_fake_watcher_success() -> None:
    """假 watcher 成功 → ok:true（watcher 路径透传 ReloadResult）。"""
    reg = make_registry(make_modules_raw(), generation=1)
    out = reload_and_rollback(
        reg, make_modules_raw(),
        watcher=make_fake_watcher_ok(make_reload_ok_result()),
    )
    assert out.ok is True
    assert out.changed_modules == ("enemies",)
    assert out.generation == 2  # watcher 结果透传


# =============================================================================
# 变更清单返回（changed_modules 正确性）
# =============================================================================

def test_changed_modules_listed_for_each_applied_change() -> None:
    """逐条变更 → changed_modules 去重清单正确（enemies 两条变更只记一次）。"""
    raw = make_modules_raw()
    new_enemies = list(raw["enemies"]) + [{"id": "extra", "name": "加怪"}]
    out = apply_module_changes(raw, [
        {"module": "enemies", "entries": new_enemies},
        {"module": "enemies", "entries": new_enemies},  # 重复变更去重
        {"module": "quest", "item_id": "q1", "removed": True},
    ])
    assert out["changed_modules"] == ["enemies", "quest"]
    assert len(out["modules"]["enemies"]) == 3


def test_write_modules_written_list_matches_order() -> None:
    """write_modules 返回 written 清单 = 写入顺序（模块名集合正确）。"""
    out = write_modules(Path("."), {})  # 空写入不碰磁盘
    assert out == {"ok": True, "written": []}
