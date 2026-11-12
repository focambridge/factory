from calc.core import add


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean() of an empty list")
    total = 0.0
    for v in values:
        total = add(total, v)
    return total / len(values)
