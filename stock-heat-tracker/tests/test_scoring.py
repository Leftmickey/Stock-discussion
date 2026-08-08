from src.scoring import composite_score, normalize_ptt, normalize_trends, score_delta


def test_normalize_trends_clamps():
    assert normalize_trends(120) == 100
    assert normalize_trends(-5) == 0
    assert normalize_trends(55) == 55


def test_normalize_ptt_increases_with_activity():
    low = normalize_ptt(1, 0)
    mid = normalize_ptt(8, 40)
    high = normalize_ptt(30, 800)
    assert 0 <= low < mid < high <= 100
    # 不應太快飽和
    assert normalize_ptt(12, 80) < 100


def test_composite_handles_partial():
    assert composite_score(80, None) == 80
    assert composite_score(None, 40) == 40
    assert composite_score(80, 40) == 60
    assert composite_score(None, None) is None


def test_score_delta():
    assert score_delta(70, 50) == 20
    assert score_delta(None, 50) is None
