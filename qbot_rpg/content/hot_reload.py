"""内容包热重载：3s 轮询（mtime+哈希）→ 五段管线 → 原子指针切换 / 失败快照回退 + 失败节流防空转。

依据：
  - 细化_3e2_热重载契约 TRG-2（检测判据 = mtime + 哈希）、TRG-3（增量：mtime 未变复用解析，引用仍全量重跑）、
    TRG-4（新模块入监控）、TRG-5（未声明文件不加载）
  - 细化_3e2_热重载契约 F2/ATO-3~7（新配置整体全量校验 → 通过才指针级切换 → 失败不发布 → 绝不半套配置运行）
  - 细化_3e2_热重载契约 F3/SNAP-1~3（N=2 档快照；失败回退上一份校验通过 + 人话提示；D-04）
  - 细化_3e2_热重载契约 BLK-5（连续失败≥3 → 自动暂停自动轮询转手动；恢复 = 文件恢复合法或手动 /重载；防空转）
  - 细化_3e_loader校验接线 §4.1（3 秒自动检测 / /重载 手动）、§4.4（快照回退流程 1-4 步）

零 NoneBot；仅依赖 qbot_rpg.content.models/validator/loader/registry/field_meta。
"""

from __future__ import annotations

import asyncio
import json
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Deque, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.loader import PackLoadError, build_pack, file_signature
from qbot_rpg.data.logging_utils import get_logger

_logger = get_logger("content.hot_reload")

from qbot_rpg.content.models import (
    FieldMetaTable,
    PackError,
    PackWarning,
    ValidationReport,
)
from qbot_rpg.content.registry import Registry, RegistrySnapshot

DEFAULT_POLL_INTERVAL_S = 3.0  # 细化_3e2 D-01：默认 3 秒（可配）
DEFAULT_MAX_CONSECUTIVE_FAILURES = 3  # 细化_3e2 D-04/BLK-5：防空转阈值


def _log_report_counts(
    pack_id: str,
    errors: Tuple[PackError, ...],
    warnings: Tuple[PackWarning, ...],
    *,
    prefix: str = "热重载",
) -> None:
    """红/黄计数日志（WIR-11 / F4 验收③ 可观测出口）。

    启动路径红拦阻断记「红 N / 黄 M」计数 + 逐模块明细（模块名可定位）；
    黄提示计数在成功/失败路径都必须落日志（现状仅失败路径记错误数）。
    """
    _logger.warning(
        "%s %s：红 %d / 黄 %d（error(s)=%d warning(s)=%d）",
        prefix, pack_id, len(errors), len(warnings), len(errors), len(warnings),
    )
    grouped: Dict[str, Tuple[int, int]] = {}
    for e in errors:
        grouped.setdefault(e.module, (0, 0))
        grouped[e.module] = (grouped[e.module][0] + 1, grouped[e.module][1])
    for w in warnings:
        grouped.setdefault(w.module, (0, 0))
        grouped[w.module] = (grouped[w.module][0], grouped[w.module][1] + 1)
    for module, (n_err, n_warn) in sorted(grouped.items()):
        if n_err or n_warn:
            _logger.debug("  模块 %s：红 %d / 黄 %d", module, n_err, n_warn)


def schedule_polling(
    watcher: "HotReloadWatcher",
    interval_s: float = DEFAULT_POLL_INTERVAL_S,
) -> Callable[[], Awaitable["ReloadResult"]]:
    """轮询调度包装（WIR-04 / C-3）：返回可测 async 闭包，供壳层 apscheduler 定时驱动。

    零 apscheduler import（调度注册归批次6/7，nonebot_plugin_apscheduler）：
        scheduler.add_job(schedule_polling(watcher, interval_s), "interval", seconds=interval_s)
    每次调用 = watcher.poll_once() 单次「检测→有变更才重载」；无变更返回 no change 结果不重载。
    interval_s 作为包装契约可配参数暴露（实际节拍由调度器决定），并存于闭包供可测断言。

    【工程补白】本函数是批次6/7 apscheduler 注册的「poll 调度包装契约」落点；
    本批零 apscheduler import，NoneBot 侧注册归批次6/7（细化_3e §4.1 / 规则 L110）。
    """
    async def _poll() -> "ReloadResult":
        return await watcher.poll_once()

    _poll.interval_s = float(interval_s)  # type: ignore[attr-defined]  # 可测闭包暴露间隔
    _poll.watcher = watcher  # type: ignore[attr-defined]
    return _poll


@dataclass(frozen=True)
class ReloadResult:
    """单次热重载结果（结构化；人话提示由 commands 层按 errors/warnings 翻译，D-06）。"""

    pack_id: str
    ok: bool
    changed_modules: Tuple[str, ...]  # 本次实际重新解析的模块（TRG-3 增量上报）
    warnings: Tuple[PackWarning, ...]
    errors: Tuple[PackError, ...]
    restored: bool  # 失败回退触发（快照回退，细化_3e2 F3 第②步）
    paused: bool  # 连续失败达到阈值 → 自动轮询暂停
    generation: int  # 当前 registry 世代号（自检 B 补给）
    note: str = ""  # 技术性说明（非用户文案；日志/调试用）
    no_change: bool = False  # 轮询无新事件（WIR-04/TCP-03：no change 不重载；TPL-18 触发）

    @property
    def ok_and_clean(self) -> bool:
        return self.ok and not self.warnings

    # 红/黄计数接入（WIR-11：ReloadResult 从校验报告带出计数，供翻译/日志复用）
    @property
    def count_errors(self) -> int:
        return len(self.errors)

    @property
    def count_warnings(self) -> int:
        return len(self.warnings)


class HotReloadWatcher:
    """单内容包监控器：初始装载 + 轮询 + 手动 reload + 快照回退 + 失败节流（TRG-6：只监控启用中的包）。"""

    def __init__(
        self,
        pack_dir: Path,
        meta: Optional[FieldMetaTable] = None,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        max_consecutive_failures: int = DEFAULT_MAX_CONSECUTIVE_FAILURES,
    ) -> None:
        self._pack_dir = Path(pack_dir)
        self._pack_id = self._pack_dir.name
        self._meta: FieldMetaTable = meta if meta is not None else default_field_meta_table()
        self._poll_interval_s = float(poll_interval_s)
        self._max_failures = int(max_consecutive_failures)

        # ---- 运行态 ----
        self._registry: Registry = Registry()  # 空注册表直到首次装载成功
        self._parse_cache: Dict[str, Dict[str, object]] = {}  # 增量解析缓存（TRG-3）
        self._baseline: Dict[str, Optional[Tuple[int, int, str]]] = {}  # 最近一次成功装载的签名基线
        self._last_attempt: Dict[str, object] = {}  # 最近一次尝试（含失败）的签名 → 防同签名重试
        self._snapshots: Deque[RegistrySnapshot] = deque(maxlen=2)  # N=2 档（当前有效 + 上一份）
        self._fail_count: int = 0
        self._paused: bool = False
        self._generation: int = 0
        self._last_result: Optional[ReloadResult] = None
        self._lock = asyncio.Lock()  # 串行化 reload / poll（防并发重载，§4.6）
        self._stop = asyncio.Event()
        self._running = asyncio.Event()

    # ------------------------------------------------------------------ 读接口
    @property
    def registry(self) -> Registry:
        return self._registry

    @property
    def pack_id(self) -> str:
        return self._pack_id

    @property
    def generation(self) -> int:
        return self._generation

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def last_result(self) -> Optional[ReloadResult]:
        return self._last_result

    @property
    def consecutive_failures(self) -> int:
        return self._fail_count

    # ------------------------------------------------------------------ 生命周期
    async def start(self) -> ReloadResult:
        """首次装载（启动路径）：走完整五段管线；失败即抛 PackLoadError（启动必须可运行）。

        WIR-03 / ADR-D3-01：首轮装载失败 = 启动失败——抛 PackLoadError 前记
        「红 N / 黄 M」计数 + 逐模块明细日志（WIR-11/12，F4 验收③ 可观测）；
        装配层捕获后拒绝提供服务，不对外暴露带病空 registry。
        """
        async with self._lock:
            result = await asyncio.to_thread(self._reload_sync, "start")
        if not result.ok:
            # WIR-11：启动路径红拦阻断 → 红/黄计数 + 逐模块明细（F4 验收③）
            _log_report_counts(self._pack_id, result.errors, result.warnings, prefix="启动装载红拦")
            raise PackLoadError(ValidationReport(errors=result.errors, warnings=result.warnings))
        if result.warnings:
            # WIR-11：黄提示计数在启动路径也必须落日志（F4 统一口径 = _log_report_counts）
            _log_report_counts(self._pack_id, result.errors, result.warnings, prefix="启动装载")
        return result

    async def reload(self, pack_id: Optional[str] = None) -> ReloadResult:
        """手动 /重载：立即执行同一条管线（不等待 3 秒，TRG-1 同源）。

        pack_id 仅作接口兼容（单包框架，细化_3e2 TRG-6「插件只能启用一个数据包」）。
        """
        async with self._lock:
            return await asyncio.to_thread(self._reload_sync, "manual")

    async def run(self) -> None:
        """后台轮询循环：每 poll_interval_s（默认 3s）检测变更（TRG-1/T1）。

        防空转（BLK-5）：`_detect_changes` 按「签名≠基线 且 ≠最近尝试」过滤，
        失败路径会把触发源写进 `_last_attempt`，同签名坏包不再 3s 空转；
        连续失败达阈值 → 置 `_paused`（P1-1 2026-08-24：paused 期间本循环
        **完全停止自动检测与重载**，转手动 /reload 才可触发——BLK-5「自动
        暂停自动轮询重载、转手动」兑现；手动 reload() 成功即复位）。停止用 stop()。

        【设计收敛 C-3，2026-08-18】：定稿《开发规则》L110「定时任务统一走
        nonebot_plugin_apscheduler」是硬约束。本方法保留为 **M0 零依赖可测默认**
        （asyncio 循环，可脱机单测）；M4 壳层接线时将改用 `poll_once()` +
        apscheduler 定时驱动（见 poll_once docstring），本方法届时收归壳层调度。
        """
        self._running.set()
        while not self._stop.is_set():
            if self._paused:
                # BLK-5：自动暂停——不做变更检测、不重载（省 IO、防空转）；
                # 作者新保存也不自动触发，须手动 /reload（成功后 _commit_success 复位）
                await asyncio.sleep(self._poll_interval_s)
                continue
            events = await asyncio.to_thread(self._detect_changes)
            if events:
                # 新事件（签名 ≠ 基线 且 ≠ 上次尝试）：把触发源传给 _reload_sync，
                # 失败路径据此写防空转签名（build_pack 抛异常时它自己拿不到 changed）
                async with self._lock:
                    await asyncio.to_thread(self._reload_sync, "poll", tuple(events))
            await asyncio.sleep(self._poll_interval_s)
        self._running.clear()

    async def poll_once(self) -> ReloadResult:
        """单次轮询检测 + 重载（C-3 收敛：供 M4 壳层用 apscheduler 定时驱动）。

        与 run() 的区别：不自行 while+sleep，每次调用做一次变更检测——
        有「新事件」才重载；无新事件直接返回（防空转逻辑与 run() 完全一致，
        同签名坏包不重复触发）。P1-1（2026-08-24）：paused 时直接返回
        last_result / no change，不检测不重载（BLK-5 自动暂停语义，与 run() 一致）。
        M4 接线示例（nonebot_plugin_apscheduler）：

            scheduler.add_job(watcher.poll_once, "interval", seconds=3)

        返回：本次 ReloadResult（无变更时返回 last_result 或「no change」占位结果）。
        """
        if self._paused:
            # BLK-5：自动暂停——不做检测/重载，返回最近结果（转手动 /reload）
            prev = self._last_result
            if prev is not None:
                return prev
            return ReloadResult(
                pack_id=self._pack_id, ok=True, changed_modules=(), warnings=(), errors=(),
                restored=False, paused=True, generation=self._generation,
                note="paused（BLK-5 自动暂停，需手动 /reload）",
            )
        events = await asyncio.to_thread(self._detect_changes)
        if not events:
            # WIR-04 / TCP-03：无新事件 → 返回 no_change 结果（no_change=True，供
            # TPL-18「内容包无变更」翻译判定；不重载、不覆盖 _last_result）。
            return ReloadResult(
                pack_id=self._pack_id, ok=True, changed_modules=(), warnings=(), errors=(),
                restored=False, paused=self._paused, generation=self._generation,
                note="no change", no_change=True,
            )
        async with self._lock:
            return await asyncio.to_thread(self._reload_sync, "poll", tuple(events))

    async def stop(self) -> None:
        self._stop.set()

    # ------------------------------------------------------------------ 检测
    def _current_declared(self) -> List[str]:
        """监控文件集 = manifest 声明模块（TRG-4/TRG-5：未声明不监控；新增声明即纳入）。

        manifest 若无法解析（非法 JSON），回退到最近一次成功装载的监听集（基线）。
        """
        watch: set = set(self._baseline.keys()) - {"manifest"}
        try:
            raw = json.loads((self._pack_dir / "manifest.json").read_text(encoding="utf-8"))
            mods = raw.get("modules", [])
            if isinstance(mods, list):
                watch |= {m for m in mods if isinstance(m, str)}
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            pass
        return sorted(watch)

    def _detect_changes(self) -> List[str]:
        """变更检测（TRG-2：mtime+hash 签名；同签名不重复触发 → 防空转核心）。

        返回「新事件」模块列表：签名 ≠ 最近成功基线 且 ≠ 最近尝试（含失败），
        即仅作者新保存/新文件触发，坏包不空转重试。
        """
        changes: List[str] = []
        manifest_path = self._pack_dir / "manifest.json"
        msig = file_signature(manifest_path)
        if msig != self._baseline.get("manifest"):
            if self._last_attempt.get("manifest") != msig:
                changes.append("manifest")
        for m in self._current_declared():
            sig = file_signature(self._pack_dir / f"{m}.json")
            if sig != self._baseline.get(m) and self._last_attempt.get(m) != sig:
                changes.append(m)
        return changes

    # ------------------------------------------------------------------ 管线（同步，to_thread 内执行）
    def _reload_sync(
        self, source: str, detected: Optional[Tuple[str, ...]] = None
    ) -> ReloadResult:
        """热重载 = 重走五段管线（细化_3e §4.2 / F2）：

        ① 快照当前有效 registry（旧配置不变，天然可用）
        ② 增量解析 + 全量校验（新配置整体，ATO-3）
        ③ 红拦/异常 → 不发布（新对象弃用）+ 回退旧快照（字节一致，L178）+ 失败记账/节流（BLK-5）
        ④ 通过 → 构建新 registry（generation+1）→ 指针级替换（D-03）→ 基线更新 + 快照入队（N=2）

        :param detected: 本次触发源（_detect_changes 的 events）。失败路径用它写
            `_last_attempt` 签名（build_pack 抛异常时无法得到 changed，缺此防空转失效）。
        """
        pre = self._registry.snapshot()  # ① 快照（回退对象）
        changed: Tuple[str, ...] = ()
        report_errors: Tuple[PackError, ...] = ()
        report_warnings: Tuple[PackWarning, ...] = ()
        note = ""

        try:
            pack, changed = build_pack(
                self._pack_dir, self._meta, self._parse_cache, self._generation + 1
            )
        except PackLoadError as exc:
            report_errors = exc.errors
            report_warnings = exc.report.warnings
            note = f"load blocked by {len(report_errors)} red-block error(s)"
            # WIR-11：失败路径记红/黄计数（F4 统一口径 = _log_report_counts，含逐模块明细）
            _log_report_counts(self._pack_id, report_errors, report_warnings, prefix="热重载红拦")
        except Exception as exc:  # IO/意外异常 → 按校验失败处理（SNAP-2）
            report_errors = (
                PackError("pack", "pack", "R-5",
                          dict(rule="unexpected_error", error=type(exc).__name__, message=str(exc))),
            )
            note = f"unexpected load error: {type(exc).__name__}"
            # 规则 ⑪⑫：意外异常记完整堆栈（logger.exception），随后走快照回退兜底
            _logger.exception("hot_reload %s 意外加载异常（回退旧 registry）", self._pack_id)
        else:
            # ③ 通过后自检 A（接口完整性，细化_3e2 自检 A）
            issue = pack.registry.integrity_check()
            if issue is not None:
                report_errors = (PackError("pack", "registry", "R-5",
                                           dict(rule="integrity_check", detail=issue)),)
                note = f"integrity check failed: {issue}"
            else:
                return self._commit_success(pack, changed, source)

        # ---- 失败路径（SNAP-1~3 / BLK-5）----
        # ② 恢复内存指向 = 最近一次校验通过的 registry（pre 即当前有效，回退保证字节一致，L178）
        self._registry = Registry.from_snapshot(pre)
        # 防同签名空转：记录本次失败文件的签名（坏包不重复打转；新保存改动签名才再触发）。
        # build_pack 抛异常时拿不到 changed，必须回退到调用方传入的 detected（触发源）。
        failed_mods = tuple(detected) if detected else changed
        for m in failed_mods:
            self._last_attempt[m] = file_signature(self._pack_dir / f"{m}.json")
        if "manifest" in failed_mods:
            self._last_attempt["manifest"] = file_signature(self._pack_dir / "manifest.json")
        self._fail_count += 1
        paused = self._fail_count >= self._max_failures
        if paused:
            self._paused = True
            note = (note + " | ") if note else ""
            note += f"consecutive failures >= {self._max_failures}: auto-poll paused (manual /reload still works)"
        result = ReloadResult(
            pack_id=self._pack_id,
            ok=False,
            changed_modules=changed,
            warnings=report_warnings,
            errors=report_errors,
            restored=True,
            paused=paused,
            generation=self._generation,
            note=note + f" [source={source}]",
        )
        self._last_result = result
        return result

    def _commit_success(self, pack, changed: Tuple[str, ...], source: str) -> ReloadResult:
        """④ 成功路径：指针级替换 + 双快照 + 基线/节流复位。"""
        new_reg: Registry = pack.registry
        # 指针级替换（单引用写；期间旧引用继续服务，D-03 / 细化_3e §1.5）
        self._registry = new_reg
        self._generation = new_reg.generation
        # 基线 = 当前所有声明模块的最新签名（未变更模块基线本就相同；缺失= None）
        baseline: Dict[str, Optional[Tuple[int, int, str]]] = {"manifest": file_signature(self._pack_dir / "manifest.json")}
        for m in self._current_declared():
            baseline[m] = file_signature(self._pack_dir / f"{m}.json")
        self._baseline = baseline
        self._last_attempt = {}
        self._snapshots.append(self._registry.snapshot())  # N=2 档滚动（上一次校验通过快照保留）
        self._fail_count = 0
        self._paused = False  # 文件恢复合法 → 自动恢复轮询（BLK-5 恢复条件）
        # F3 修复（M6 批3A 审查）：changed 为空（手动 /重载 缓存命中无实际变更）→
        # no_change=True → 上层走 TPL-18「内容包无变更」，不误报「0 个模块变更生效」。
        result = ReloadResult(
            pack_id=self._pack_id,
            ok=True,
            changed_modules=changed,
            warnings=pack.report.warnings,
            errors=(),
            restored=False,
            paused=False,
            generation=self._generation,
            no_change=(not changed),
            note=f"reloaded {len(changed)} changed module(s) [source={source}]",
        )
        self._last_result = result
        return result

    def backup_snapshot(self) -> RegistrySnapshot:
        """当前有效 registry 快照（RSM-05：激活 _backup_snapshot 死代码 → 公开接口）。

        对外供旧局旧配置结算引用（细化_3e2 OLD-1/OLD-2）；续战世代重绑定取档
        经本接口 + _snapshots（N=2 滚动）双口。与 _snapshots 区别：本接口返回
        「当前有效档」（= 最近一次校验通过快照），_snapshots 另含上一份（回退用）。
        """
        return self._registry.snapshot()


__all__ = [
    "HotReloadWatcher",
    "ReloadResult",
    "schedule_polling",
    "DEFAULT_POLL_INTERVAL_S",
    "DEFAULT_MAX_CONSECUTIVE_FAILURES",
]
