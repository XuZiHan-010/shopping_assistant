from app.services.seed_service import default_merchants


def test_default_seed_contains_three_reproducible_borough_merchants() -> None:
    first = default_merchants(merchant_count=3)
    second = default_merchants(merchant_count=3)

    assert first == second
    assert len(first) == 3
    assert len({merchant.id for merchant in first}) == 3
    assert len({merchant.merchant_code for merchant in first}) == 3
    assert first[0].display_name == "Borough商家100"


def test_seed_can_expand_deterministically_for_isolation_tests() -> None:
    merchants = default_merchants(merchant_count=5)

    assert len(merchants) == 5
    assert merchants[3].merchant_code == "borough-demo-103"
    assert merchants[4].display_name == "Borough商家104"
