from calc.stats import value_range


def test_value_range():
    assert value_range([3, 10, 7]) == 7
