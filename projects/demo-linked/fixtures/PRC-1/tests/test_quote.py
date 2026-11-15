import json
from pathlib import Path

import pytest
from jsonschema import validate

from pricing.quote import quote

CONTRACT = json.loads((Path(__file__).parents[1] / "contracts" / "quote.schema.json").read_text())


def test_quote_apple():
    assert quote("apple", 3) == {"sku": "apple", "quantity": 3, "unit_price_pence": 40, "total_pence": 120}


def test_unknown_sku():
    with pytest.raises(KeyError):
        quote("durian", 1)


def test_matches_contract():
    validate(quote("pear", 2), CONTRACT)
