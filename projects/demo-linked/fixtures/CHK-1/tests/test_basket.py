from checkout.basket import total


def fake_quote(sku, quantity):
    return {"sku": sku, "quantity": quantity, "unit_price_pence": 10, "total_pence": 10 * quantity}


def test_total():
    assert total([("a", 2), ("b", 3)], fake_quote) == 50


def test_empty_basket():
    assert total([], fake_quote) == 0
