"""3f 内容包校验器单测（scripts/check_m7_content.py · M7 BCH-09 3f F-18 · R-27）。

覆盖三场景：① 隐藏要素可达性（前置条件键未注册/引用不可解析 → RED 提示不阻断）；
② 条件键白名单（未注册键/未登记事件报清单，已注册不报）；③ 模板占位符（未定义 {X}
报提示，合法占位符不报）；④ main 退出码（0=通过 / 1=有提示 / 2=目录不可读）。
脚本经 importlib 加载（scripts 无 __init__.py，对齐 test_quality_gate 模式）。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import tempfile

_CHECK = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "check_m7_content.py"
_spec = importlib.util.spec_from_file_location("check_m7_content_mod", _CHECK)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # noqa: E402  (module-level sys.path 引导，qbot_rpg 已可 import)


# -------------------------------------------------------------------------------------
# 测试夹具：JSON 内容包写入工具（tmp dir 内构建）
# -------------------------------------------------------------------------------------
def _write(pack: pathlib.Path, name: str, data) -> None:
    """把 JSON 数据写入包内 {name}。"""
    (pack / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_pack(td: str, name: str) -> pathlib.Path:
    """建空内容包目录。"""
    p = pathlib.Path(td) / name
    p.mkdir()
    return p


def _clean_pack(td: str) -> pathlib.Path:
    """干净内容包（无隐藏要素/无未注册键/无非法占位符）→ 三项校验全过。"""
    p = _make_pack(td, "clean")
    _write(p, "maps.json", [
        {"id": "m1", "name": "乱石滩", "desc": "安静的入口。",
         "monsters": [{"enemy": "rock_weasel", "count": 2}], "exits": {}},
    ])
    _write(p, "enemies.json", [
        {"id": "rock_weasel", "name": "岩皮鼬", "desc": "普通野兽。"},
    ])
    return p


def _bad_reachability_pack(td: str) -> pathlib.Path:
    """隐藏 BOSS window 引用未注册条件键 + 隐藏地图引用不存在 map → RED 不可达。"""
    p = _make_pack(td, "bad_reach")
    _write(p, "maps.json", [
        {"id": "m1", "name": "雾沼", "monsters": [
            {"enemy": "rock_weasel", "count": 1},
            {"enemy": "ghost_wolf",
             "window": {"var": "ghost_condition_key", "op": "eq", "param": "X"},
             "event_id": "rain_night", "hidden_find_id": "hf_wolf"},
        ]},
        {"id": "m2", "name": "雾沼深处",
         "hidden_reveal": {"map_ref": "m3",
                           "lore_condition": {"var": "level", "op": "ge", "value": 5}},
         "monsters": []},
    ])
    _write(p, "enemies.json", [
        {"id": "rock_weasel", "name": "岩皮鼬", "desc": "普通野兽。"},
    ])
    return p


def _bad_whitelist_pack(td: str) -> pathlib.Path:
    """未注册条件键 + 未登记事件名（黄提示清单）。"""
    p = _make_pack(td, "bad_whitelist")
    _write(p, "maps.json", [
        {"id": "m1", "name": "入口", "monsters": [
            {"enemy": "rock_weasel",
             "spawn_condition": {"var": "unregistered_var", "op": "ge", "value": 1}},
        ]},
    ])
    _write(p, "enemies.json", [
        {"id": "rock_weasel", "name": "岩皮鼬",
         "ambient": "现身于{未知}之间。",
         "lore_condition": {"var": "[事件:不存在的事件]", "op": "ge", "value": 1}},
    ])
    return p


def _placeholder_pack(td: str) -> pathlib.Path:
    """模板占位符：未定义 {X} 报提示，合法占位符不报。"""
    p = _make_pack(td, "bad_placeholder")
    _write(p, "maps.json", [
        {"id": "m1", "name": "山道",
         "desc": "今日{季节}，{时段}的{天气}适合赶路，但{未知变量}让人不安。",
         "monsters": []},
    ])
    _write(p, "enemies.json", [])
    return p


# -------------------------------------------------------------------------------------
# 校验 1：隐藏要素可达性
# -------------------------------------------------------------------------------------
def test_reachability_unregistered_condition_red():
    """前置条件键未注册 → RED 不可达（无发现路径=可能永不可发现），提示性不阻断。"""
    with tempfile.TemporaryDirectory() as td:
        p = _bad_reachability_pack(td)
        issues = _mod.check_hidden_reachability(_mod.build_index(str(p)))
        reds = [i for i in issues if i["level"] == "RED"]
        assert any("ghost_condition_key" in i["msg"] and "永不可发现" in i["msg"]
                   for i in reds)
        # m2 hidden_reveal 引用的 m3 未在 maps.json → 引用不可解析报红
        assert any("m3" in i["msg"] and "无法解析" in i["msg"] for i in reds)


def test_reachability_clean_no_issues():
    """干净包：无隐藏要素 → 可达性零提示。"""
    with tempfile.TemporaryDirectory() as td:
        p = _clean_pack(td)
        issues = _mod.check_hidden_reachability(_mod.build_index(str(p)))
        assert issues == []


# -------------------------------------------------------------------------------------
# 校验 2：条件键白名单
# -------------------------------------------------------------------------------------
def test_whitelist_unregistered_keys_listed():
    """全文扫描 → 未注册条件键 + 未登记事件报清单（黄提示）。"""
    with tempfile.TemporaryDirectory() as td:
        p = _bad_whitelist_pack(td)
        issues = _mod.check_condition_whitelist(_mod.build_index(str(p)))
        assert any("unregistered_var" in i["msg"] for i in issues)
        assert any("[事件:不存在的事件]" in i["msg"] and "未在事件注册表" in i["msg"]
                   for i in issues)
        assert all(i["level"] == "YELLOW" for i in issues)


def test_whitelist_registered_keys_clean():
    """已注册条件键（[季节]/level/[事件:任务完成]/[图鉴完成度]）→ 不报。"""
    with tempfile.TemporaryDirectory() as td:
        p = _make_pack(td, "wl_ok")
        _write(p, "maps.json", [
            {"id": "m1", "name": "雾沼", "monsters": [
                {"enemy": "rock_weasel",
                 "spawn_condition": [
                     {"var": "[季节:秋]", "op": "eq"},
                     {"var": "level", "op": "ge", "value": 5},
                     {"var": "[事件:任务完成]", "op": "ge", "value": 1},
                     {"var": "[图鉴完成度]", "op": "ge", "value": 50},
                 ]},
            ]},
        ])
        _write(p, "enemies.json", [])
        issues = _mod.check_condition_whitelist(_mod.build_index(str(p)))
        assert issues == []


def test_whitelist_env_event_registered_via_pack():
    """[事件:环境事件:X] 引用包内自声明 env_event_id → 已登记不报；未声明 → 报提示。"""
    with tempfile.TemporaryDirectory() as td:
        p = _make_pack(td, "wl_env")
        _write(p, "maps.json", [
            {"id": "m1", "name": "雾沼", "monsters": [
                {"enemy": "rock_weasel",
                 "spawn_condition": {"var": "[事件:环境事件:rain_night]", "op": "ge",
                                     "value": 1}},
            ]},
        ])
        _write(p, "enemies.json", [])
        issues = _mod.check_condition_whitelist(_mod.build_index(str(p)))
        assert any("rain_night" in i["msg"] and "未在包内声明" in i["msg"] for i in issues)
        # 补声明（窗口行 event_id）后不报
        _write(p, "maps.json", [
            {"id": "m1", "name": "雾沼", "monsters": [
                {"enemy": "rock_weasel",
                 "spawn_condition": {"var": "[事件:环境事件:rain_night]", "op": "ge",
                                     "value": 1}},
                {"enemy": "boss",
                 "window": {"var": "weather", "op": "eq", "param": "雷雨"},
                 "event_id": "rain_night"},
            ]},
        ])
        issues2 = _mod.check_condition_whitelist(_mod.build_index(str(p)))
        assert not any("rain_night" in i["msg"] for i in issues2)


# -------------------------------------------------------------------------------------
# 校验 3：模板占位符
# -------------------------------------------------------------------------------------
def test_placeholders_undefined_reported():
    """未定义 {X} 占位符报提示；合法占位符不报。"""
    with tempfile.TemporaryDirectory() as td:
        p = _placeholder_pack(td)
        issues = _mod.check_placeholders(_mod.build_index(str(p)))
        # 夹具仅 1 个未定义占位符 {未知变量} → 恰 1 条提示；{季节}/{时段}/{天气} 不报
        assert len(issues) == 1
        assert issues[0]["level"] == "YELLOW"
        assert "未知变量" in issues[0]["msg"] and "未定义占位符" in issues[0]["msg"]


def test_placeholders_legal_only_no_issues():
    """仅合法占位符（含 R-14 的 {图鉴完成度}）→ 零提示。"""
    with tempfile.TemporaryDirectory() as td:
        p = _make_pack(td, "ph_ok")
        _write(p, "maps.json", [
            {"id": "m1", "name": "雾沼",
             "desc": "今日{季节}的{时段}，{天气}笼罩，图鉴完成度{图鉴完成度}%。",
             "monsters": []},
        ])
        _write(p, "enemies.json", [])
        assert _mod.check_placeholders(_mod.build_index(str(p))) == []


# -------------------------------------------------------------------------------------
# 主入口退出码（0=通过 / 1=有提示 / 2=目录不可读）
# -------------------------------------------------------------------------------------
def test_main_exit_clean_pack():
    """干净包 → exit 0（通过无提示）。"""
    with tempfile.TemporaryDirectory() as td:
        p = _clean_pack(td)
        assert _mod.main(["--path", str(p)]) == 0


def test_main_exit_advisory_pack():
    """有提示（不可达/未注册/占位符）→ exit 1（提示性不阻断）。"""
    with tempfile.TemporaryDirectory() as td:
        p = _bad_whitelist_pack(td)
        assert _mod.main(["--path", str(p)]) == 1


def test_main_exit_missing_dir():
    """内容包目录不存在 → exit 2。"""
    assert _mod.main(["--path", "/no/such/pack/dir"]) == 2
