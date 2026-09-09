"""转职白值重算单测（2026-09-09 用户拍板：职业成长跟随职业）。"""
from qbot_rpg.core.levelup import rebase_white_for_job_change
from qbot_rpg.data.player import PlayerAttributes


def _attrs(**base):
    a = PlayerAttributes()
    a.base.update({k: float(v) for k, v in base.items()})
    return a


def test_rebase_growth_delta():
    """level 10 脊剑士（atk growth 10/dfn 6.5）→ 新职业（atk growth 8/dfn 7）：
    base 含 9 级旧成长 → 补差后 atk = 旧 - 9×2、dfn = 旧 + 9×0.5。"""
    a = _attrs(atk=100.0 + 9 * 10.0, dfn=50.0 + 9 * 6.5, hp=400.0 + 9 * 12.0)
    affected = rebase_white_for_job_change(
        a, 10,
        {"atk": 10.0, "dfn": 6.5, "hp": 12.0},
        {"atk": 8.0, "dfn": 7.0, "hp": 10.0},
    )
    assert a.base["atk"] == 100.0 + 9 * 8.0
    assert a.base["dfn"] == 50.0 + 9 * 7.0
    assert a.base["hp"] == 400.0 + 9 * 10.0
    assert set(affected) == {"atk", "dfn", "hp"}


def test_rebase_preserves_free_points():
    """自由加点混存 base：补差只动成长差，额外自由点保留。"""
    a = _attrs(atk=100.0 + 9 * 10.0 + 15.0)  # +15 自由点
    rebase_white_for_job_change(a, 10, {"atk": 10.0}, {"atk": 12.0})
    assert a.base["atk"] == 100.0 + 9 * 12.0 + 15.0


def test_rebase_level1_noop():
    """1 级无历史成长：不补差。"""
    a = _attrs(atk=100.0)
    affected = rebase_white_for_job_change(a, 1, {"atk": 10.0}, {"atk": 12.0})
    assert affected == []
    assert a.base["atk"] == 100.0


def test_rebase_same_job_noop():
    """同职业转职（旧==新）：delta 0 无变化。"""
    a = _attrs(atk=190.0)
    affected = rebase_white_for_job_change(a, 10, {"atk": 10.0}, {"atk": 10.0})
    assert affected == []
    assert a.base["atk"] == 190.0


def test_rebase_growth_key_union():
    """新职业新增/删除成长键：并集补差（新键从 0 起算，旧键归 0）。"""
    a = _attrs(atk=190.0, mag=0.0)
    rebase_white_for_job_change(
        a, 10,
        {"atk": 10.0, "mag": 1.0},
        {"atk": 5.0},  # mag 不再成长
    )
    assert a.base["atk"] == 100.0 + 9 * 5.0
    assert a.base["mag"] == 0.0 + 9 * (0.0 - 1.0)  # 旧成长回退
