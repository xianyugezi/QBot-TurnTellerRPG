"""故障注入脚本③ fault_inject_reload.py（M6 批5·路B · D5 FLT 件套）——TC-FLT-10/11 热重载失败回退。

依据：
  - 细化_M6_故障注入.md（D5）§四：FLT-18（注入点 = 向启用中包写非法 JSON 后触发 watcher.reload()，
    reload 走同一条管线 TRG-1）/ FLT-19（回退上一份校验通过 registry：ReloadResult.restored=True、
    errors 非空、generation 不变、registry 内容 = 上一份校验通过快照原子替换未污染）/
    FLT-20（服务不崩 + 人话提示经 D3 WIR-09/10 翻译 → TPL-16 失败回退模板）/
    FLT-21（恢复路径：还原合法 JSON 再 reload 成功 generation+1）+ TC-FLT-10/11
  - 细化_M6_热重载接线.md（D3）§1.4：TPL-16 `❌ 重载失败，已回退旧配置：{原因}。请修正配置后保存，
    或手动 /重载 重试`（WIR-09/10）+ §1.5 TC-WIR-07/13（坏包回退不崩、恢复后可重载）
  - 细化_3e2_热重载契约：SNAP-1~3（N=2 档快照；失败回退上一份校验通过 registry + 人话提示）、
    ATO-4（校验失败不替换内存引用，服务继续运行在旧配置上）、D-04（快照滚动）
  - 细化_5d_测试体系总纲 L205-208（注入隔离纪律：夹具内注入、独立 tmp_path、恢复路径 finally）

工程决策（对齐 D5 §四 / 任务批5·路B）：
  - 真实 HotReloadWatcher + tmp_path 复制 legal 合法包（FLT-04：独立测试包，不触碰共享 fixture 源目录）
  - 注入点 = 向启用中包写入非法 JSON（截断 effects.json 制造 R-5 invalid_json 红拦）→ watcher.reload()
  - 断言对象 = ReloadResult.restored/errors/generation + registry 内容未污染 + render_reload_result
    输出 TPL-16 人话（原因 + 正确用法 + 下一步）
  - 恢复路径 = 每个用例 finally 从源包还原合法 effects.json（FLT-21 / 5d L205-208，失败不污染后续用例）

零 NoneBot import；仅依赖 content 层 HotReloadWatcher + commands 层 render_reload_result 纯函数。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Tuple

import pytest

from qbot_rpg.commands.reload_result import render_reload_result
from qbot_rpg.content.hot_reload import HotReloadWatcher, ReloadResult

# legal 合法包源（tests/fixtures/packs/legal，test_content.py FIX_DIR 同款定位）；只读源，
# 测试一律复制到 tmp_path 独立包，绝不直接改写（FLT-04 注入隔离）。
_LEGAL_PACK = Path(__file__).resolve().parents[1] / "fixtures" / "packs" / "legal"

# 非法 JSON 注入载荷（截断的 JSON → R-5 invalid_json 红拦）
_INVALID_JSON = '{"id": "broken",'


@pytest.fixture
def legal_copy(tmp_path: Path) -> Path:
    """独立测试包 fixture（FLT-04）：复制 legal 合法包到 tmp_path，返回包目录。

    每用例独立 tmp_path，互不串扰；源目录 tests/fixtures/packs/legal 只读不写。
    """
    dst = tmp_path / "legal"
    shutil.copytree(_LEGAL_PACK, dst)
    return dst


def _registry_ids(watcher: HotReloadWatcher) -> Tuple[Tuple[str, ...], Tuple[str, ...]]:
    """读取 registry 关键表 ID 快照（item + effect 两表），供「未污染」断言对照。"""
    return tuple(watcher.registry.all_ids("item")), tuple(watcher.registry.all_ids("effect"))


# ---------------------------------------------------------------------------------------
# TC-FLT-10：非法 JSON → 回退旧 registry + 人话提示（FLT-18~20 / D3 WIR-09/10）
# ---------------------------------------------------------------------------------------
async def test_flt10_invalid_json_rollback_old_registry_and_tpl16(legal_copy: Path) -> None:
    """三要素注释（FLT-03 / 5d L205-208）：
    注入点 = 向启用中包写非法 JSON（截断 effects.json → R-5 invalid_json）后 watcher.reload()
            （FLT-18，reload 与 poll_once 同一管线 TRG-1）；
    断言对象 = ReloadResult.restored=True + errors 非空 + generation 不变（FLT-19）+ registry 两表
            ID 未污染（原子快照回退，无半套配置）+ render_reload_result 输出 TPL-16 人话（FLT-20）+
            连续失败计数 1（未达阈值不暂停，服务持续可用）；
    恢复路径 = finally 从源包还原合法 effects.json（FLT-21 / 5d L205-208）。"""
    watcher = HotReloadWatcher(legal_copy, max_consecutive_failures=3)
    first = await watcher.start()
    assert first.ok, f"start 应装载成功: {first.note}"
    gen_before = watcher.generation
    item_ids_before, eff_ids_before = _registry_ids(watcher)

    try:
        # 注入：向启用中包写入非法 JSON（截断 effects.json）
        (legal_copy / "effects.json").write_text(_INVALID_JSON, encoding="utf-8")
        result: ReloadResult = await watcher.reload()

        # ---- 断言对象 ----
        assert result.ok is False, "非法 JSON 重载必须失败"
        assert result.restored is True, "失败必须回退上一份校验通过 registry（FLT-19）"
        assert len(result.errors) > 0, "errors 必须非空（红拦明细）"
        assert any(e.kind == "R-5" for e in result.errors), "截断 JSON 应红拦 R-5 invalid_json"
        assert result.generation == gen_before, f"回退后 generation 不变（{gen_before}）"
        # registry 未污染：原子快照回退 → 内容 = 上一份校验通过快照
        item_ids_after, eff_ids_after = _registry_ids(watcher)
        assert item_ids_after == item_ids_before, "回退后 item 表不得被污染"
        assert eff_ids_after == eff_ids_before, "回退后 effect 表不得被污染"
        assert watcher.consecutive_failures == 1, "单次失败计数=1（未达阈值不暂停）"
        assert watcher.paused is False, "单次失败不暂停自动轮询（服务持续可用）"
        # 人话提示：TPL-16（原因 + 正确用法 + 下一步，WIR-09/10）
        msg = render_reload_result(result, consecutive_failures=watcher.consecutive_failures)
        assert "重载失败，已回退旧配置" in msg, f"应输出 TPL-16 回退头部: {msg}"
        assert "effects.json" in msg, "原因应含模块定位（首个红拦人话）"
        assert "请修正配置后保存，或手动 /重载 重试" in msg, "应含正确用法 + 下一步"
    finally:
        # 恢复路径：还原合法 effects.json（失败/断言中断也不污染）
        shutil.copy(_LEGAL_PACK / "effects.json", legal_copy / "effects.json")


# ---------------------------------------------------------------------------------------
# TC-FLT-11：恢复后可重载（FLT-21 / 3e2 TC-06）
# ---------------------------------------------------------------------------------------
async def test_flt11_recover_legal_json_reload_ok_generation_plus_one(legal_copy: Path) -> None:
    """三要素注释（FLT-03 / 5d L205-208）：
    注入点 = 非法 JSON 触发 reload 回退后，恢复合法 JSON 再 reload（FLT-21，TC-FLT-10 已回退前置）；
    断言对象 = 第二次 reload 成功（ok=True、restored=False）+ generation+1 + 连续失败计数清零、
            paused=False（服务不崩、可继续重载，3e2 TC-06 / WIR-05 恢复条件）；
    恢复路径 = finally 从源包还原合法 effects.json（幂等，5d L205-208）。"""
    watcher = HotReloadWatcher(legal_copy, max_consecutive_failures=3)
    first = await watcher.start()
    assert first.ok, f"start 应装载成功: {first.note}"
    gen_before = watcher.generation

    try:
        # 前置：写入非法 JSON → reload 回退（TC-FLT-10 状态）
        (legal_copy / "effects.json").write_text("{ not json", encoding="utf-8")
        bad: ReloadResult = await watcher.reload()
        assert bad.ok is False and bad.restored is True, "前置回退成立"

        # 恢复：还原合法 JSON（与源包字节一致）→ 再 reload
        (legal_copy / "effects.json").write_text(
            (_LEGAL_PACK / "effects.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        good: ReloadResult = await watcher.reload()

        # ---- 断言对象 ----
        assert good.ok is True, f"恢复合法 JSON 后重载应成功: {good.note}"
        assert good.restored is False, "成功后不标记回退"
        assert good.generation == gen_before + 1, f"成功重载 generation+1（{gen_before}→{good.generation}）"
        assert watcher.consecutive_failures == 0, "成功后失败计数清零（BLK-5 恢复条件）"
        assert watcher.paused is False, "成功后自动轮询恢复"
        # 服务不崩、新配置生效：effects 表可解析（heal_small 为 legal 包既有 effect ID）
        assert watcher.registry.resolve("heal_small", "effect") is not None, "重载后新配置可用"
    finally:
        # 恢复路径：还原合法 effects.json（幂等）
        shutil.copy(_LEGAL_PACK / "effects.json", legal_copy / "effects.json")
