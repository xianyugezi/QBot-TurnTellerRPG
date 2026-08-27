"""ApiResponse 统一返回格式单测（通用规则 ㉒）。"""
from __future__ import annotations

from qbot_rpg.data.api_response import CODE_ERROR, CODE_OK, ApiResponse


def test_ok_default() -> None:
    r = ApiResponse.ok()  # type: ignore[var-annotated]
    assert r.code == CODE_OK == 0
    assert r.msg == "success"
    assert r.data == {}
    assert r.success is True


def test_ok_with_data() -> None:
    r = ApiResponse.ok(data={"name": "阿伟", "level": 35}, msg="查询成功")
    assert r.code == 0
    assert r.msg == "查询成功"
    assert r.data == {"name": "阿伟", "level": 35}


def test_error() -> None:
    r = ApiResponse.error(code=2, msg="玩家不存在")  # type: ignore[var-annotated]
    assert r.code == 2
    assert r.msg == "玩家不存在"
    assert r.data == {}
    assert r.success is False


def test_to_dict_shape() -> None:
    """㉒：对外序列化必须形如 {"code":..,"msg":..,"data":..}。"""
    r = ApiResponse.ok(data=[1, 2, 3])
    d = r.to_dict()
    assert set(d.keys()) == {"code", "msg", "data"}
    assert d["code"] == 0 and d["msg"] == "success" and d["data"] == [1, 2, 3]


def test_code_constants() -> None:
    assert CODE_OK == 0
    assert CODE_ERROR == 1