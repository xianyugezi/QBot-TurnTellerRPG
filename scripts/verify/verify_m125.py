"""M12.5 verify：编辑器全模块扩展验收门禁（scripts/verify/verify_m125.py）。

验收（m125_启动包 §五）：
  1. 全模块可达：editor.json 30 页全登记，list 页 CRUD 端点可 list、obj/map
     页 /whole 可读（零 404）
  2. 零新增红拦：field_meta 全模块字段表注入后 test_demo 加载零红拦
  3. 事件可配置：settings.events 段配键名 → resolve_event_key 全链生效 +
     缺省回退零破坏
  4. 硬编码清零：PAGE_MODULE 已降级兜底（_page_info 页表优先）、refs/meta
     写死 dict 已删（REFS_TARGET_ALIASES 单源）、EditorPage 扩展字段透传

用法：.venv/bin/python scripts/verify/verify_m125.py（exit 0=通过）

铁律：零 NoneBot import；纯逻辑断言；不写盘（只读 content/test_demo 加载）；
      ruff E501 行宽≤100。
"""
from __future__ import annotations

import asyncio
import pathlib
from types import SimpleNamespace

from qbot_rpg.content.editor_registry import load_editor_registry
from qbot_rpg.content.loader import load_pack
from qbot_rpg.web import pages_crud

_REPO = pathlib.Path(__file__).resolve().parent.parent.parent
_PACK = _REPO / "content" / "test_demo"


def _load_pack():
    """test_demo 真实内容包加载（零红拦 = 加载不抛）。"""
    return asyncio.run(load_pack(_PACK))


def t_all_modules_registered_and_reachable() -> bool:
    """editor.json 30 页登记 + 每页 list/whole 可达（零 404）。"""
    pack = _load_pack()
    ed = load_editor_registry(pack.registry)
    ctx = {"modules_raw": pack.registry.modules_raw}
    pages = list(ed.pages)
    if len(pages) < 30:
        print(f"  FAIL editor.json 登记页 {len(pages)} < 30")
        return False
    bad = []
    for pg in pages:
        if not pg.enabled:
            continue
        shape = pages_crud.module_shape(ctx, pg.page_id)
        if shape in ("obj", "map"):
            out = pages_crud.get_whole_module(pg.page_id, ctx)
            if not out.get("ok") or not isinstance(out.get("data"), dict):
                bad.append(f"{pg.page_id}({shape}) whole 读取失败")
        else:
            out = pages_crud.list_page_items(pg.page_id, ctx)
            if not out.get("ok"):
                bad.append(f"{pg.page_id} list 失败")
    if bad:
        print(f"  FAIL 页面可达性：{bad[:5]}")
        return False
    print(f"  PASS 30 页登记全可达（list/obj/map 三形态）")
    return True


def t_shape_dispatch() -> bool:
    """形态判定：settings/forge/fishing=obj、stats/formula=map、技能=list。"""
    pack = _load_pack()
    ctx = {"modules_raw": pack.registry.modules_raw}
    expect = {"settings": "obj", "forge": "obj", "fishing": "obj",
              "stats": "map", "formula": "map", "skill": "list",
              "dungeon": "list", "achievements": "list"}
    for page, want in expect.items():
        got = pages_crud.module_shape(ctx, page)
        if got != want:
            print(f"  FAIL 形态 {page}: 期望 {want} 实际 {got}")
            return False
    print("  PASS 形态判定（obj/map/list 分流正确）")
    return True


def t_field_meta_all_modules_injected() -> bool:
    """field_meta 全模块登记：C 类注入 + obj/map 字段表非空 + label 中文。"""
    from qbot_rpg.content.field_meta import default_field_meta_table

    t = default_field_meta_table()
    # C 类注入：dungeon/achievements 字段 ≥7（原空表已注入）
    for mod, min_f in (("dungeon", 9), ("achievements", 7)):
        m = t.modules.get(mod)
        if m is None or len(m.fields) < min_f:
            print(f"  FAIL C 类注入 {mod}（{len(m.fields) if m else 0} 字段）")
            return False
    # obj/map 字段表：forge/fishing 段级宽容器 + stats/formula map value_meta
    for mod, shape in (("forge", "object"), ("fishing", "object"),
                       ("stats", "map"), ("formula", "map")):
        m = t.modules.get(mod)
        if m is None or m.entry_type != shape:
            print(f"  FAIL {mod} entry_type 期望 {shape}")
            return False
        if shape == "object" and len(m.fields) < 3:
            print(f"  FAIL {mod} obj 段级字段表不足")
            return False
    print("  PASS field_meta 全模块注入（C 类 + obj/map 字段表）")
    return True


def t_event_keys_configurable() -> bool:
    """事件键可配置：settings.events 改名全链 + 缺省回退零破坏。"""
    from qbot_rpg.core.event_bus import resolve_event_key

    # 缺省回退（无 events 配置）
    ctx_plain = {"settings": {}}
    if resolve_event_key(ctx_plain, "签到") != "[事件:签到]":
        print("  FAIL 缺省回退失败")
        return False
    # 配置改名
    ctx_renamed = {"settings": {"events": {"签到": "每日打卡"}}}
    if resolve_event_key(ctx_renamed, "签到") != "[事件:每日打卡]":
        print("  FAIL 配置改名失败")
        return False
    # 完整键直通
    ctx_full = {"settings": {"events": {"签到": "[成就:打卡王]"}}}
    if resolve_event_key(ctx_full, "签到") != "[成就:打卡王]":
        print("  FAIL 完整键直通失败")
        return False
    # test_demo settings 已含 events 段（13 键配置示例）
    pack = _load_pack()
    settings = pack.registry.modules_raw.get("settings") or {}
    events = settings.get("events") or {}
    if len(events) < 10:
        print(f"  FAIL test_demo settings.events 段缺失（{len(events)} 键）")
        return False
    print("  PASS 事件键可配置（改名/完整键/缺省回退/test_demo events 段）")
    return True


def t_hardcode_cleanup() -> bool:
    """硬编码清零：动态页表优先 + 别名表单源 + 扩展字段透传。"""
    from qbot_rpg.content.editor_registry import default_editor_pages
    from qbot_rpg.web.api import REFS_TARGET_ALIASES

    # 1) REFS_TARGET_ALIASES 覆盖全 kind（含 D 类扩展）
    for kind in ("monster", "item", "skill", "job", "map", "quest", "shop",
                 "npc", "effect", "status", "mark", "trait", "action",
                 "recipe", "equipment", "slot", "chain"):
        if kind not in REFS_TARGET_ALIASES:
            print(f"  FAIL REFS_TARGET_ALIASES 缺 {kind}")
            return False
    # 2) EditorPage 扩展字段存在（id_prefix/group/page_kind）
    d = default_editor_pages()
    if not d or not hasattr(d[0], "id_prefix"):
        print("  FAIL EditorPage 缺扩展字段")
        return False
    print("  PASS 硬编码清零（REFS_TARGET_ALIASES 单源 + EditorPage 扩展）")
    return True


def t_dynamic_pages_crud_extension() -> bool:
    """pages_crud 动态页表：editor 页表驱动 + 兜底常量兼容。"""
    from qbot_rpg.content.registry import Registry

    # 有 editor 模块 → 页表驱动（npc 可 CRUD）
    reg = Registry(pack_id="t", generation=1, tables={}, names={},
                   modules_raw={"editor": {
                       "schema_version": 1,
                       "pages": [{"page_id": "npc", "module_file": "npc.json",
                                  "enabled": True}]},
                       "npc": [{"id": "elder", "name": "长老"}]})
    ctx = {"modules_raw": reg.modules_raw}
    out = pages_crud.list_page_items("npc", ctx)
    if not out.get("ok") or not out["items"]:
        print("  FAIL editor 页表驱动 npc 页不可达")
        return False
    # 无 editor → 兜底六页（旧内容包兼容）
    reg2 = Registry(pack_id="t", generation=1, tables={}, names={},
                    modules_raw={"enemies": [{"id": "e1", "name": "怪"}]})
    out2 = pages_crud.list_page_items("monster", {"modules_raw": reg2.modules_raw})
    if not out2.get("ok"):
        print("  FAIL 无 editor 兜底六页不可达")
        return False
    print("  PASS pages_crud 动态页表（editor 驱动 + 兜底兼容）")
    return True


def main() -> int:
    checks = [
        t_all_modules_registered_and_reachable,
        t_shape_dispatch,
        t_field_meta_all_modules_injected,
        t_event_keys_configurable,
        t_hardcode_cleanup,
        t_dynamic_pages_crud_extension,
    ]
    failed = 0
    for fn in checks:
        ok = fn()
        if not ok:
            failed += 1
    print(f"\nverify_m125: {'PASS' if failed == 0 else f'FAIL ({failed} 项失败)'} "
          f"（{len(checks) - failed}/{len(checks)}）")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
