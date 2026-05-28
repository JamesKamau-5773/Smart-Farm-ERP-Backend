import pytest

from app.services.feed_frequency_helper import FeedFrequencyHelper


def test_calculate_schedule_basic():
    out = FeedFrequencyHelper.calculate_milking_schedule(20)
    assert out['target_liters'] == 20.0
    assert out['total_dairy_meal_kg'] >= 0
    assert out['used_milking_frequency'] in (2, 3, 4)


def test_calculate_with_override():
    out = FeedFrequencyHelper.calculate_milking_schedule(50, baseline_herd_meal_kg=4.0, milking_frequency=3)
    assert out['used_milking_frequency'] == 3
    assert out['per_milking_session_kg'] * 3 == pytest.approx(out['extra_milking_topup_total_kg'], rel=1e-3)


def test_invalid_inputs():
    with pytest.raises(ValueError):
        FeedFrequencyHelper.calculate_milking_schedule('not-a-number')

    with pytest.raises(ValueError):
        FeedFrequencyHelper.calculate_milking_schedule(-5)

    with pytest.raises(ValueError):
        FeedFrequencyHelper.calculate_milking_schedule(20, milking_frequency=0)
