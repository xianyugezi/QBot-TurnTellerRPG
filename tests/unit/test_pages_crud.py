"""编辑器六页 CRUD 纯逻辑层单测（tests/unit/test_pages_crud.py · M12 批1 路1C）。

依据：docs/细化/细化_5a_编辑器契约.md §6.3（L176-181：列表/详情/新建/更新/删除/
validate 语义）+ SV-03 红拦 5 类（L126）/ SV-04 黄提示（L127）+ TC-01 ID 自动生成
（L214 skill_0001）+ 级联删除（L180）。

覆盖：
  - list_page_items：分页/搜索（q）/排序（sort/-sort）
  - get_page_item：单条详情 + 引用字段中文名 refs
  - create_page_item：ID 自动生成 `类型_序号` 不冲突 / 重复 id 拒绝
  - update_page_item：版本冲突 409 / 合并更新 / id 不可改
  - delete_page_item：级联（怪物→地图 monsters/gate_guard）+ cascades 清单
  - validate_page_item：红（负数/类型/结构 min>max）黄（引用未登记/名字长）分级

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性；无 emoji；
      新测试文件 ruff E501 零豁免（行宽 ≤100）。
"""
from __future__ import annotations

from qbot_rpg.web.pages_crud import (
    PAGE_MODULE,
    apply_delete_to_entries,
    create_page_item,
    delete_page_item,
    get_page_item,
    list_page_items,
    update_page_item,
    validate_page_item,
)

# =============================================================================
# 假 modules_raw（dict 直填，模拟 loader 解析产物：顶层 list + id/name）
# =============================================================================
def make_ctx(**over):
    """CRUD ctx：modules_raw 是可变 dict（delete 级联会原地改它）。"""
    ctx = {
        "modules_raw": {
            "enemies": [
                {"id": "gust_wolf", "name": "风狼", "hp": 90, "atk": 12},
                {"id": "ridge_cub", "name": "脊冢幼兽", "hp": 90, "atk": 8},
            ],
            "maps": [
                {"id": "forest", "name": "风语森林", "monsters": [
                    {"enemy": "gust_wolf"}, {"enemy": "ridge_cub"}],
                 "exits": {"north": {"to": "cave"}}},
                {"id": "cave", "name": "洞穴", "monsters": [{"enemy": "gust_wolf"}],
                 "gate_guard": "gust_wolf"},
            ],
            "skills": [
                {"id": "slash", "name": "脊斩", "job_restrict": ["ridge_blade"]},
            ],
            "jobs": [{"id": "ridge_blade", "name": "脊剑士"}],
            "quest": [{"id": "q1", "name": "讨伐风狼", "reward": [{"item": "potion"}]}],
            "shop": [{"id": "s1", "name": "杂货店", "items": [{"item": "potion"}]}],
            "items": [{"id": "potion", "name": "药水"}],
        },
    }
    ctx.update(over)
    return ctx


# =============================================================================
# 列表：分页/搜索/排序
# =============================================================================
def test_list_all_pages_default():
    """列表无参 → 全量条目（total 正确）。"""
    out = list_page_items("monster", make_ctx())
    assert out["ok"] is True
    assert out["total"] == 2
    assert [i["id"] for i in out["items"]] == ["gust_wolf", "ridge_cub"]


def test_list_search_q():
    """q=脊 → 名字匹配（子串，大小写不敏感）。"""
    out = list_page_items("monster", make_ctx(), q="脊")
    assert out["total"] == 1
    assert out["items"][0]["id"] == "ridge_cub"


def test_list_pagination():
    """page/size 分页切片。"""
    out = list_page_items("monster", make_ctx(), page_no=2, size=1)
    assert out["total"] == 2
    assert [i["id"] for i in out["items"]] == ["ridge_cub"]


def test_list_sort_desc():
    """sort=-atk → 攻击倒序（数值）。"""
    out = list_page_items("monster", make_ctx(), sort="-atk")
    assert [i["id"] for i in out["items"]] == ["gust_wolf", "ridge_cub"]


def test_list_unknown_page():
    """未知 page → ok:false + red 404。"""
    out = list_page_items("ghost", make_ctx())
    assert out["ok"] is False
    assert out["errors"][0]["level"] == "red"


def test_quest_module_is_quest_singular():
    """契约 P-06 quests.json 笔误修正：quest 页 module=quest（loader 登记）。"""
    assert PAGE_MODULE["quest"] == "quest"


# =============================================================================
# 详情：引用中文名
# =============================================================================
def test_get_item_with_refs():
    """map 详情 monsters 引用 → refs 中文名解析（monsters 行 enemy 键 → monster 引用）。"""
    out = get_page_item("map", "forest", make_ctx())
    assert out["ok"] is True
    assert out["item"]["id"] == "forest"
    # monsters 列表内 enemy 引用（dict 行）→ refs["monster"] 中文名
    assert out["refs"].get("monster", {}).get("gust_wolf") == "风狼"
    assert out["refs"].get("monster", {}).get("ridge_cub") == "脊冢幼兽"
    # exits 通道 to 引用（非 refs 扫描范围，但详情本身完整）
    assert out["item"]["exits"]["north"]["to"] == "cave"


def test_get_item_not_found():
    """条目不存在 → 404 red。"""
    out = get_page_item("monster", "ghost", make_ctx())
    assert out["ok"] is False
    assert out["errors"][0]["code"] == "not_found"


# =============================================================================
# 新建：ID 生成
# =============================================================================
def test_create_auto_id():
    """无 id → 自动生成 monster_0001（类型_序号，4 位零填充）。"""
    ctx = make_ctx()
    out = create_page_item("monster", {"name": "新怪", "hp": 50}, ctx)
    assert out["ok"] is True
    assert out["id"] == "monster_0001"
    # 再次生成 → 序号递增（条目数 3）
    out2 = create_page_item("monster", {"name": "又一只", "hp": 40}, ctx)
    assert out2["id"] == "monster_0002"


def test_create_existing_prefix_continues():
    """已有 monster_0005 → 新生成 monster_0006（取最大序号 + 1）。"""
    ctx = make_ctx()
    ctx["modules_raw"]["enemies"].append(
        {"id": "monster_0005", "name": "旧序号", "hp": 1})
    out = create_page_item("monster", {"name": "新怪", "hp": 2}, ctx)
    assert out["id"] == "monster_0006"


def test_create_dup_id_rejected():
    """显式 id 已存在 → red dup_id。"""
    out = create_page_item("monster", {"id": "gust_wolf", "name": "重复"}, make_ctx())
    assert out["ok"] is False
    assert out["errors"][0]["code"] == "dup_id"


def test_create_sets_version_zero():
    """新建条目版本簿置 0（编辑锁基线）。"""
    ctx = make_ctx()
    out = create_page_item("monster", {"name": "新怪", "hp": 1}, ctx)
    assert ctx["_page_versions"]["enemies"][out["id"]] == 0


# =============================================================================
# 更新：版本冲突 409
# =============================================================================
def test_update_ok_and_version_bump():
    """更新成功 → 合并字段 + 版本自增。"""
    ctx = make_ctx()
    out = update_page_item("monster", "gust_wolf",
                           {"hp": 120}, base_version=0, ctx=ctx)
    assert out["ok"] is True
    assert out["item"]["hp"] == 120
    assert out["item"]["name"] == "风狼"  # 未提交字段保留
    assert out["version"] == 1


def test_update_version_conflict_409():
    """base_version 与当前不符 → 409（code=409 + red version_conflict）。"""
    ctx = make_ctx()
    # 先更新一次（版本 0→1）
    update_page_item("monster", "gust_wolf", {"hp": 120}, base_version=0, ctx=ctx)
    # 旧 base_version=0 再来 → 冲突
    out = update_page_item("monster", "gust_wolf", {"hp": 999}, base_version=0, ctx=ctx)
    assert out["ok"] is False
    assert out.get("code") == 409
    assert out["errors"][0]["code"] == "version_conflict"


def test_update_id_immutable():
    """id 字段不可改（更新忽略 id）。"""
    ctx = make_ctx()
    out = update_page_item("monster", "gust_wolf",
                           {"id": "hacked"}, base_version=0, ctx=ctx)
    assert out["ok"] is True
    assert out["item"]["id"] == "gust_wolf"


def test_update_not_found():
    """条目不存在 → 404。"""
    out = update_page_item("monster", "ghost", {"hp": 1}, base_version=0, ctx=make_ctx())
    assert out["ok"] is False


# =============================================================================
# 删除：级联
# =============================================================================
def test_delete_monster_cascades_maps():
    """删怪物 gust_wolf → maps monsters[] 移除 + gate_guard 清空，cascades 齐。"""
    ctx = make_ctx()
    out = delete_page_item("monster", "gust_wolf", ctx)
    assert out["ok"] is True
    assert out["id"] == "gust_wolf"
    # forest monsters 移除 gust_wolf 保留 ridge_cub
    forest = ctx["modules_raw"]["maps"][0]
    assert [m["enemy"] for m in forest["monsters"]] == ["ridge_cub"]
    # cave gate_guard 清空 + monsters 移除
    cave = ctx["modules_raw"]["maps"][1]
    assert cave["gate_guard"] == ""
    assert cave["monsters"] == []
    # cascades 清单覆盖两张图的 monsters 移除 + cave gate_guard
    assert any(c["removed_ref"]["field"] == "gate_guard" for c in out["cascades"])
    assert len(out["cascades"]) >= 3


def test_delete_job_cascades_skills_job_restrict():
    """删职业 ridge_blade → skills[].job_restrict[] 剔除。"""
    ctx = make_ctx()
    out = delete_page_item("job", "ridge_blade", ctx)
    assert out["ok"] is True
    slash = ctx["modules_raw"]["skills"][0]
    assert slash["job_restrict"] == []
    assert any(c["removed_ref"]["field"] == "job_restrict" for c in out["cascades"])


def test_delete_map_cascades_exits():
    """删地图 cave → 其它图 exits to==cave 移除。"""
    ctx = make_ctx()
    out = delete_page_item("map", "cave", ctx)
    assert out["ok"] is True
    forest = ctx["modules_raw"]["maps"][0]
    assert "north" not in forest["exits"]  # north.to==cave 被移除
    assert any(c["removed_ref"]["field"] == "exits.north" for c in out["cascades"])


# =============================================================================
# M12.5 批2 路2A：删物品级联（enemies.drops/shop.items/quest.reward/recipe +
#    quest/npc 条件 param/var 引用阻止删除）
# =============================================================================
def make_items_ctx(**over):
    """删物品场景假数据：potion 被敌人掉落/商店/任务奖励/配方多处引用。

    items 页非六页兜底（PAGE_MODULE 不含）——按批1 路1A 语义经 editor 模块
    页表登记（module_file=items.json）后才可 CRUD（对齐 make_editor_ctx）。
    """
    ctx = {
        "modules_raw": {
            "editor": {
                "schema_version": 1,
                "pages": [
                    {"page_id": "items", "title": "物品", "icon": "🎒",
                     "module_file": "items.json", "meta_source": "meta/items",
                     "enabled": True, "validator": "items"},
                    {"page_id": "quest", "title": "任务", "icon": "📜",
                     "module_file": "quest.json", "meta_source": "meta/quest",
                     "enabled": True, "validator": "quest"},
                    {"page_id": "shop", "title": "商店", "icon": "🏪",
                     "module_file": "shop.json", "meta_source": "meta/shop",
                     "enabled": True, "validator": "shop"},
                ],
            },
            "enemies": [
                {"id": "gust_wolf", "name": "风狼", "drops": {
                    "battle": [{"item": "potion", "chance": 50}],
                    "special": [], "death": []}},
                {"id": "ridge_cub", "name": "脊冢幼兽", "drops": {
                    "battle": [], "special": [{"item": "potion", "chance": 10}],
                    "death": [{"item": "potion", "chance": 100}]}},
            ],
            "shop": [
                {"id": "village_shop", "name": "杂货店",
                 "items": [{"item": "potion", "price": 100},
                           {"item": "antidote", "price": 60}]},
            ],
            "quest": [
                {"id": "q1", "name": "备药", "reward": [{"coins": 50},
                                                       {"item": "potion", "count": 1}]},
            ],
            "recipe": [
                {"id": "rcp1", "name": "合成", "materials": [{"id": "potion", "count": 1}],
                 "output": {"item": "elixir", "count": 1}},
            ],
            "items": [{"id": "potion", "name": "药水"},
                      {"id": "antidote", "name": "解毒草"},
                      {"id": "lonely_pebble", "name": "孤石"}],
        },
    }
    ctx.update(over)
    return ctx


def test_delete_item_cascades_drops_shop_reward():
    """删物品 potion → enemies.drops.*/shop.items/quest.reward 引用行全清，cascades 齐。"""
    ctx = make_items_ctx()
    out = delete_page_item("items", "potion", ctx)
    assert out["ok"] is True
    raw = ctx["modules_raw"]
    # enemies：battle/special/death 三容器内 potion 行全移除
    assert raw["enemies"][0]["drops"]["battle"] == []
    assert raw["enemies"][1]["drops"]["special"] == []
    assert raw["enemies"][1]["drops"]["death"] == []
    # shop.items：potion 行移除、antidote 保留
    assert raw["shop"][0]["items"] == [{"item": "antidote", "price": 60}]
    # quest.reward：potion 行移除、coins 行保留
    assert raw["quest"][0]["reward"] == [{"coins": 50}]
    # cascades 覆盖三模块 + drops 子键 field 记 drops.battle 形态
    # （recipe materials 命中另计——见 test_delete_item_cascades_recipe）
    mods = {c["module"] for c in out["cascades"]}
    assert mods >= {"enemies", "shop", "quest"}
    fields = [c["removed_ref"]["field"] for c in out["cascades"]
              if c["module"] != "recipe"]  # recipe 命中在 recipe 用例里单独断言
    assert "drops.battle" in fields and "drops.special" in fields and "drops.death" in fields
    assert "items" in fields and "reward" in fields
    assert len(out["cascades"]) == 6  # drops×3 + shop + quest.reward + recipe.materials
    assert all(c["removed_ref"]["value"] == "potion" for c in out["cascades"])


def test_delete_item_cascades_recipe():
    """删物品 potion → recipe materials 行移除；output 指别的物品则原样保留。"""
    ctx = make_items_ctx()
    out = delete_page_item("items", "potion", ctx)
    assert out["ok"] is True
    rcp = ctx["modules_raw"]["recipe"][0]
    assert rcp["materials"] == []
    assert rcp["output"] == {"item": "elixir", "count": 1}  # output 引用 elixir 不受影响
    assert any(c["removed_ref"]["field"] == "materials" for c in out["cascades"])
    assert not any(c["removed_ref"]["field"] == "output" for c in out["cascades"])


def test_delete_item_recipe_output_ref_cleared():
    """recipe.output.item==删除物品 → output 置空 + cascades 记 output 字段。"""
    ctx = make_items_ctx()
    ctx["modules_raw"]["recipe"][0]["output"] = {"item": "potion", "count": 2}
    out = delete_page_item("items", "potion", ctx)
    assert out["ok"] is True
    rcp = ctx["modules_raw"]["recipe"][0]
    assert rcp["output"] == {}
    assert any(c["removed_ref"]["field"] == "output" for c in out["cascades"])


def test_delete_item_blocked_by_quest_condition_param():
    """potion 被 quest.conditions[].param 引用 → 阻止删除（in_use），零级联。"""
    ctx = make_items_ctx()
    ctx["modules_raw"]["quest"][0]["conditions"] = [
        {"var": "item_count", "op": "ge", "value": 1, "param": "potion"}]
    raw = ctx["modules_raw"]
    raw["enemies"][0]["drops"]["battle"] = [{"item": "potion", "chance": 50}]
    out = delete_page_item("items", "potion", ctx)
    assert out["ok"] is False
    assert out["errors"][0]["code"] == "in_use"
    assert "q1" in out["errors"][0]["message"]
    # 引用方未动：掉落行原样保留
    assert raw["enemies"][0]["drops"]["battle"] == [{"item": "potion", "chance": 50}]


def test_delete_item_unreferenced_ok():
    """删无任何引用（且无条件引用）的孤石 → ok，cascades 空。"""
    ctx = make_items_ctx()
    out = delete_page_item("items", "lonely_pebble", ctx)
    assert out["ok"] is True
    assert out["cascades"] == []
    # 引用了 potion 的行不受影响
    assert ctx["modules_raw"]["shop"][0]["items"][0]["item"] == "potion"


def test_delete_not_found():
    """删除不存在条目 → 404。"""
    out = delete_page_item("monster", "ghost", make_ctx())
    assert out["ok"] is False


def test_apply_delete_removes_entry():
    """apply_delete_to_entries：条目从 modules_raw 移除，返回新列表。"""
    ctx = make_ctx()
    out = apply_delete_to_entries("monster", "gust_wolf", ctx)
    assert out["ok"] is True
    assert out["module"] == "enemies"
    assert [e["id"] for e in out["entries"]] == ["ridge_cub"]
    assert ctx["modules_raw"]["enemies"] == out["entries"]


# =============================================================================
# 草稿校验：红/黄分级
# =============================================================================
def test_validate_red_negative():
    """负数 → red（SV-03 ②）。"""
    out = validate_page_item("monster", {"id": "x", "name": "怪", "hp": -5}, make_ctx())
    assert any(e["level"] == "red" and e["code"] == "negative" for e in out["red"])


def test_validate_red_type_error():
    """数字填文字 → red type_error（SV-03 ①）。"""
    out = validate_page_item("monster", {"id": "x", "name": "怪", "hp": "abc"}, make_ctx())
    assert any(e["level"] == "red" and e["code"] == "not_number" for e in out["red"])


def test_validate_red_struct_min_max():
    """条件 min>max → red struct（SV-03 ⑤ 死配置）。"""
    out = validate_page_item("monster", {"id": "x", "name": "怪",
                                         "min": 10, "max": 5}, make_ctx())
    assert any(e["level"] == "red" and e["code"] == "struct" for e in out["red"])


def test_validate_red_missing_id():
    """缺 id → red struct 必填。"""
    out = validate_page_item("monster", {"name": "无id"}, make_ctx())
    assert any(e["level"] == "red" and e["code"] == "struct" for e in out["red"])


def test_validate_yellow_long_name():
    """名字 >20 字 → yellow。"""
    out = validate_page_item("monster", {"id": "x", "name": "名" * 25}, make_ctx())
    assert any(e["level"] == "yellow" and e["code"] == "range" for e in out["yellow"])


def test_validate_yellow_unregistered_ref():
    """引用未登记（enemy 查无）→ yellow ref_unregistered。"""
    ctx = make_ctx()
    out = validate_page_item("map", {"id": "m", "name": "图", "enemy": "ghost_beast"}, ctx)
    assert any(e["level"] == "yellow" and e["code"] == "ref_unregistered"
               for e in out["yellow"])


def test_validate_clean_item():
    """合法条目 → 零红零黄。"""
    out = validate_page_item("monster", {"id": "ok", "name": "正常怪",
                                         "hp": 100, "atk": 10}, make_ctx())
    assert out["red"] == []
    assert out["yellow"] == []


def test_validate_unknown_page():
    """未知 page → ok:false。"""
    out = validate_page_item("ghost", {}, make_ctx())
    assert out["ok"] is False


# =============================================================================
# M12.5 路1A：editor 模块页表动态驱动（扩展页 CRUD 打通）
# =============================================================================
def make_editor_ctx(**over):
    """带 editor 模块页表的 ctx（模拟 editor.json 12 页登记 + 各模块数据）。"""
    ctx = {
        "modules_raw": {
            "editor": {
                "schema_version": 1,
                "pages": [
                    {"page_id": "skill", "title": "技能", "icon": "⚔️",
                     "module_file": "skills.json", "meta_source": "meta/skill",
                     "enabled": True, "validator": "skill"},
                    {"page_id": "monster", "title": "怪物", "icon": "👹",
                     "module_file": "enemies.json", "meta_source": "meta/monster",
                     "enabled": True, "validator": "monster"},
                    {"page_id": "npc", "title": "NPC", "icon": "🧙",
                     "module_file": "npc.json", "meta_source": "meta/npc",
                     "enabled": True, "validator": "npc"},
                    {"page_id": "checkin", "title": "签到", "icon": "📅",
                     "module_file": "checkin.json", "meta_source": "meta/checkin",
                     "enabled": True, "validator": "checkin", "id_prefix": "chk"},
                    {"page_id": "ai", "title": "AI", "icon": "🤖",
                     "module_file": "enemies.json", "meta_source": "meta/ai",
                     "enabled": True, "validator": "ai", "extends": "monster"},
                    {"page_id": "secret", "title": "隐藏页", "icon": "🔮",
                     "module_file": "hidden.json", "meta_source": "meta/hidden",
                     "enabled": False},
                ],
            },
            "enemies": [
                {"id": "gust_wolf", "name": "风狼", "hp": 90, "atk": 12},
            ],
            "npc": [
                {"id": "elder", "name": "长老", "dialog": "你好"},
            ],
            "checkin": [
                {"id": "chk_0001", "name": "每日签到", "cycle": "day"},
            ],
            "hidden": [
                {"id": "h1", "name": "彩蛋"},
            ],
        },
    }
    ctx.update(over)
    return ctx


def test_registry_extension_page_crud_npc():
    """editor 页表登记 npc → list/get/create/update/delete 全通。"""
    ctx = make_editor_ctx()
    # list
    out = list_page_items("npc", ctx)
    assert out["ok"] is True
    assert [i["id"] for i in out["items"]] == ["elder"]
    # get
    out = get_page_item("npc", "elder", ctx)
    assert out["ok"] is True and out["item"]["name"] == "长老"
    # create（无手填 id → 自动生成 npc_0001）
    out = create_page_item("npc", {"name": "铁匠"}, ctx)
    assert out["ok"] is True
    assert out["id"] == "npc_0001"
    assert out["item"]["id"] == "npc_0001"
    # 写盘层语义：新条目合并回 modules_raw 后 update 才可见
    ctx["modules_raw"]["npc"].append(out["item"])
    # update
    out = update_page_item("npc", "npc_0001", {"name": "铁匠铺老板"}, 0, ctx)
    assert out["ok"] is True and out["item"]["name"] == "铁匠铺老板"
    # delete
    out = delete_page_item("npc", "npc_0001", ctx)
    assert out["ok"] is True
    out = apply_delete_to_entries("npc", "npc_0001", ctx)
    assert out["ok"] is True and out["module"] == "npc"


def test_registry_checkin_id_prefix():
    """页表 id_prefix=chk → 自动 ID 用 chk_ 前缀（非页名 checkin_）。"""
    ctx = make_editor_ctx()
    out = create_page_item("checkin", {"name": "周签"}, ctx)
    assert out["ok"] is True
    assert out["id"].startswith("chk_")


def test_registry_view_page_ai_reads_host_entries():
    """extends 视图页 ai（module_file=enemies.json）→ 列表复用宿主条目。"""
    ctx = make_editor_ctx()
    out = list_page_items("ai", ctx)
    assert out["ok"] is True
    assert [i["id"] for i in out["items"]] == ["gust_wolf"]


def test_registry_disabled_page_404():
    """enabled:false 的页 → 视为不存在（404 语义）。"""
    ctx = make_editor_ctx()
    out = list_page_items("secret", ctx)
    assert out["ok"] is False
    out = get_page_item("secret", "h1", ctx)
    assert out["ok"] is False
    out = create_page_item("secret", {"name": "x"}, ctx)
    assert out["ok"] is False


def test_registry_fallback_no_editor_module():
    """无 editor 模块的旧 ctx → 回退六页常量（既有测试语义保持）。"""
    out = list_page_items("monster", make_ctx())
    assert out["ok"] is True
    out = list_page_items("npc", make_ctx())  # 兜底无 npc → 404
    assert out["ok"] is False


def test_registry_settings_page_empty_list():
    """module_file=settings.json（顶层 obj 非 list）→ list 空不报错（段编辑归批4）。"""
    ctx = make_editor_ctx()
    ctx["modules_raw"]["editor"]["pages"].append(
        {"page_id": "env_event", "title": "环境事件", "icon": "🌧️",
         "module_file": "settings.json", "meta_source": "meta/env_event",
         "enabled": True, "validator": "env_event"})
    ctx["modules_raw"]["settings"] = {"default_map": "start_village"}
    out = list_page_items("env_event", ctx)
    assert out["ok"] is True
    assert out["items"] == [] and out["total"] == 0
