"""统一返回格式（通用规则 ㉒）——对外接口（web/commands 壳层）统一 {code,msg,data}。

文件名: api_response.py
创建时间: 2026-08-25
作者: Hermes（遵循用户通用规则）
功能描述: 定义模块间调用/对外接口的统一数据返回格式；内部纯逻辑层
（core/content/storage/data 引擎层）按架构定稿保持「领域对象 + 领域异常」
模式（PackLoadError/ReloadResult/ValidationReport 等），**不强制改造**——
ApiResponse 供 commands/web 等对外壳层在 M4/M6 实装时包装返回。

依据:
  - 用户通用规则 ㉒：统一数据返回格式 {"code":200,"msg":"success","data":{...}}
  - 细化_3a 架构分层契约 D-04（引擎层返回领域对象；壳层翻译人话）
  - 3a §5.2 S6 / 细化_3d §5.4（人话由 commands 层统一翻译，错误模板 TPL-12/13/14）

约定:
  - code: 0 = 成功（业务约定）；非 0 = 错误码（由各壳层定义映射）
  - msg:  供展示的简短信息（成功默认 "success"；失败由壳层翻译人话）
  - data: 业务数据对象（无数据时 {} 或 None）
零 NoneBot；仅标准库 + dataclass。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Generic, Optional, TypeVar

T = TypeVar("T")

# 业务约定：0 = 成功（非 0 为错误码，各壳层自行定义映射）
CODE_OK: int = 0
CODE_ERROR: int = 1  # 通用错误（壳层可按需细分，如 2=校验失败/3=不存在/4=权限）


@dataclass(frozen=True)
class ApiResponse(Generic[T]):
    """统一返回格式：{code, msg, data}。

    用法（对外壳层实装时）:
        return ApiResponse.ok(data=player_summary)
        return ApiResponse.error(code=2, msg="玩家不存在")
    """

    code: int = CODE_OK
    msg: str = "success"
    data: Optional[T] = field(default_factory=dict)  # type: ignore[assignment]

    def to_dict(self) -> dict:
        """序列化为 {"code":..,"msg":..,"data":..}（JSON 友好，供 web 层直接返回）。"""
        return {"code": self.code, "msg": self.msg, "data": self.data}

    @classmethod
    def ok(cls, data: Optional[T] = None, msg: str = "success") -> "ApiResponse[T]":
        return cls(code=CODE_OK, msg=msg,
                   data=data if data is not None else {})  # type: ignore[arg-type]

    @classmethod
    def error(cls, code: int = CODE_ERROR, msg: str = "error",
              data: Optional[T] = None) -> "ApiResponse[T]":
        return cls(code=code, msg=msg,
                   data=data if data is not None else {})  # type: ignore[arg-type]

    @property
    def success(self) -> bool:
        return self.code == CODE_OK


__all__ = ["ApiResponse", "CODE_OK", "CODE_ERROR"]
