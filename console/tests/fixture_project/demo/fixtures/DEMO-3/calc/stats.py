from calc.core import add, subtract


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean() of an empty list")
    total = 0.0
    for v in values:
        total = add(total, v)
    return total / len(values)


def value_range(values: list[float]) -> float:
    if not values:
        raise ValueError("value_range() of an empty list")
    return subtract(max(values), min(values))
