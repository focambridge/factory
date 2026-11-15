from checkout.basket import total
from pricing.quote import quote


def test_basket_total():
    assert total([("apple", 3), ("pear", 2)], quote) == 230
