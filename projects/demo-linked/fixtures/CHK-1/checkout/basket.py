from typing import Callable


def total(lines: list[tuple[str, int]], quote: Callable[[str, int], dict]) -> int:
    return sum(quote(sku, quantity)["total_pence"] for sku, quantity in lines)
