PRICES_PENCE = {"apple": 40, "pear": 55}


def quote(sku: str, quantity: int) -> dict:
    unit = PRICES_PENCE[sku]
    return {"sku": sku, "quantity": quantity, "unit_price_pence": unit, "total_pence": unit * quantity}
