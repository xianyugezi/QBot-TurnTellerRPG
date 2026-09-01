"""M10 钓鱼实机冒烟（部署用 · test_demo 包全链路，可复跑）。

按真实玩家流程测钓鱼：注册 → /进入 幽光林地（晨风村无钓点，须先到钓点图）→
/钓鱼 列钓点 → /钓鱼 gp_moon_grass 抛竿（等待期）→ ctx now 推进 → /鱼讯（到期
推进 S2→S3）→ /收杆 自动（出鱼结算）→ /图鉴 鱼册 → 每日对账。所有回复落盘。

确定性时钟：build_app_deps 装配 deps.dayroll 可注入 —— make_context 从
deps.dayroll() 读 (now, today) 写入 ctx["now"]（UTC+8 epoch 秒）。本脚本用
Clock 推进器：now_ts 递增，抛竿后把 now 推进到 cast_at+1 再发 /鱼讯，即可跳过
settings.fishing.wait_sec 300-900 秒的真实等待（引擎 bite_check 懒判
now >= cast_at，零定时器）。

钓点名解析（C-1 补白）：垂钓点 = maps 采集点变体，无独立 name 字段，spot 名解析
只认 id / id 前缀（/钓鱼 gp_moon_grass 精确命中；/钓鱼 月光草甸 中文名永远
「钓点不存在」）。故脚本用 id 下钩。

"""  # noqa: E501
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 仓库根

os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/test_demo"
os.environ["QBotRPG_DB_PATH"] = "/root/QBot-TurnTellerRPG/data/rpg_fishing_smoke.db"

from qbot_rpg_bridge.assemble import build_app_deps  # noqa: E402
from qbot_rpg.assembly import runner as R  # noqa: E402

TZ_UTC8 = timezone(timedelta(hours=8))
_EPOCH = datetime(2026, 9, 1, 12, 0, 0, tzinfo=TZ_UTC8)
BASE_TS = int(_EPOCH.timestamp())

CLOCK = {"ts": BASE_TS}


def _clock_dayroll():
    """注入用 dayroll：返回 (now_ts, today) —— make_context 写入 ctx["now"]。"""
    return (CLOCK["ts"], _EPOCH.strftime("%Y-%m-%d"))


def _advance(seconds: int) -> None:
    CLOCK["ts"] += seconds


FLOW = [
    "/注册",
    "/进入 上",             # 晨风村 up 通道 → gloom_forest 幽光林地（钓点图）
    "/钓鱼",                 # 应列出 gp_moon_grass 垂钓点（F-1 变体）
    "/钓鱼 gp_moon_grass",   # 抛竿（spot 名解析只认 id/前缀，C-1 补白）
    "/鱼讯",                 # ctx now 推进到 cast_at+1 → 到期 S3 鱼讯
    "/收杆 自动",            # 满力/自动 → 出鱼结算（P0-1 A5 收口）
    "/收杆 止损",            # 无会话 → 空态
    "/图鉴",                 # 总览（含鱼册完成度）
    "/图鉴 鱼",              # 鱼册分册（银鳞鲤已捕获）
]


async def main() -> None:
    deps = await build_app_deps()
    deps.dayroll = _clock_dayroll  # 确定性时钟注入（make_context 经 deps.dayroll 写 ctx["now"]）
    out: list[str] = []

    async def say(text: str, uid: str = "u_钓鱼冒烟") -> str:
        ev = {
            "group_id": "g1", "user_id": uid, "message": text,
            "message_id": str(uuid.uuid4()), "channel": "group", "group_name": "测试群",
        }
        try:
            return await asyncio.wait_for(R.run_command(ev, deps), timeout=60)
        except Exception as e:  # noqa: BLE001
            return f"[异常 {type(e).__name__}] {e}"

    for msg in FLOW:
        r = await say(msg)
        out.append(f">>> {msg}\n{(r or '(无回复/静默)')[:400]}\n---")
        if msg == "/钓鱼 gp_moon_grass":
            # 抛竿后把 now 推进到 cast_at 之后（跳过 300-900 秒等待），
            # 下一次 /鱼讯 懒判到期即出鱼讯
            _advance(3600)
    with open("/tmp/fishingflow.txt", "w", encoding="utf-8") as f:
        f.write("\n\n".join(out))

    # 简单断言：钓鱼链路至少出鱼成功一次
    joined = "\n".join(out)
    checks = {
        "进图到达钓点图": "幽光林地" in joined,
        "钓鱼列钓点": "gp_moon_grass" in joined,
        "抛竿受理": "已抛竿" in joined,
        "鱼讯推进": "鱼讯" in joined,
        "收杆结算": "出鱼成功" in joined,
        "图鉴鱼册": "银鳞鲤" in joined,
    }
    # 每日对账（R-12：日 20 次出鱼 400 − 造饵 144 ≈ 净流入 256 ±5%，确定性模型）
    try:
        from qbot_rpg.core.fishing_economy import daily_ledger_check

        ledger = daily_ledger_check({})
        checks["每日对账"] = bool(ledger.get("ok")) and abs(
            float(ledger.get("net_flow", 0)) - 256.0) <= 256.0 * 0.05
    except Exception:  # noqa: BLE001 —— 对账引擎缺失 → 断言失败不崩脚本
        checks["每日对账"] = False
    print("=== M10 钓鱼实机冒烟结果 ===")
    for k, v in checks.items():
        print(f"  {'PASS' if v else 'FAIL'}  {k}")
    ok = all(checks.values())
    print(f"总判定: {'通过' if ok else '失败（看 /tmp/fishingflow.txt 断点）'}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
