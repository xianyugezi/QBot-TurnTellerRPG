"""M13 批7 路7C 调试脚本：build_pack 红拦明细打印（临时，不落盘交付）。"""
from pathlib import Path

from qbot_rpg.content.loader import build_pack


def main() -> None:
    try:
        pack, _ = build_pack(Path("content/test_demo"))
        print("OK jobs:", len(pack.registry.all_ids("job")), "skills:", len(pack.registry.all_ids("skill")))
    except Exception as ex:  # noqa: BLE001
        rep = getattr(ex, "report", None)
        if rep is None:
            print("EXC", type(ex).__name__, ex)
            return
        for er in rep.errors:
            print("ERR", er.module, er.field, dict(er.detail))
        for w in rep.warnings:
            print("WARN", w.module, w.field, dict(w.detail))


if __name__ == "__main__":
    main()
