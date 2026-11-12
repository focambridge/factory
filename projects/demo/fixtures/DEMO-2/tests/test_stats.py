import pytest

from calc.stats import mean


def test_mean():
    assert mean([2, 4, 9]) == 5.0


def test_mean_empty():
    with pytest.raises(ValueError):
        mean([])
