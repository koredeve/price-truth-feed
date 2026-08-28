import json
import re
import decimal

PAIR = "ETH/USD"
UNKNOWN_PAIR = "DOGE/USD"

URL_ONE = "https://source-one.example.com/price"
URL_TWO = "https://source-two.example.com/price"
URL_THREE = "https://source-three.example.com/price"
URLS = [URL_ONE, URL_TWO, URL_THREE]

MEDIAN_PRICE_ATTO = 100 * 10**18


def _deploy(direct_vm, direct_deploy, owner):
    direct_vm.sender = owner
    return direct_deploy("contracts/PriceTruthFeed.py")


def _mock_sources(direct_vm, bodies=None, statuses=None):
    """Register one web mock per source URL.

    bodies/statuses are lists aligned with URLS; None entries get a
    well-formed {"price": ...} JSON body using the canonical test prices.
    """
    default_bodies = [
        json.dumps({"price": 100.0}),
        json.dumps({"price": 101.0}),
        json.dumps({"price": 99.5}),
    ]
    bodies = bodies if bodies is not None else default_bodies
    statuses = statuses if statuses is not None else [200, 200, 200]
    for url, body, status in zip(URLS, bodies, statuses):
        direct_vm.mock_web(re.escape(url), {"status": status, "body": body})


def test_owner_is_deployer_and_non_owner_cannot_set_sources(
    direct_vm, direct_deploy, direct_alice, direct_bob
):
    """The deployer becomes owner; anyone else may not configure sources."""
    contract = _deploy(direct_vm, direct_deploy, direct_alice)

    assert len(str(contract.owner())) > 0

    with direct_vm.prank(direct_bob):
        with direct_vm.expect_revert("Only owner"):
            contract.set_sources(PAIR, URLS)

    with direct_vm.expect_revert("no sources configured"):
        contract.update_price(PAIR)


def test_set_sources_requires_at_least_three_urls(
    direct_vm, direct_deploy, direct_alice
):
    """Configuring fewer than three sources is rejected."""
    contract = _deploy(direct_vm, direct_deploy, direct_alice)

    with direct_vm.expect_revert("At least three source URLs"):
        contract.set_sources(PAIR, URLS[:2])

    with direct_vm.expect_revert("no sources configured"):
        contract.update_price(PAIR)


def test_update_price_stores_median_of_three_sources(
    direct_vm, direct_deploy, direct_alice
):
    """Prices 100.0 / 101.0 / 99.5 settle the median 100.0 as atto u256."""
    contract = _deploy(direct_vm, direct_deploy, direct_alice)
    contract.set_sources(PAIR, URLS)

    _mock_sources(direct_vm)
    contract.update_price(PAIR)

    assert contract.get_price(PAIR) == MEDIAN_PRICE_ATTO
    assert contract.get_update_count(PAIR) == 1


def test_update_price_skips_one_malformed_source_and_still_resolves(
    direct_vm, direct_deploy, direct_alice
):
    """A malformed-JSON source is skipped; two live sources still settle a price."""
    contract = _deploy(direct_vm, direct_deploy, direct_alice)
    contract.set_sources(PAIR, URLS)

    _mock_sources(
        direct_vm,
        bodies=[
            '{"price": not-a-number',
            json.dumps({"price": 101.0}),
            json.dumps({"price": 99.0}),
        ],
    )
    contract.update_price(PAIR)

    assert contract.get_price(PAIR) == 101 * 10**18
    assert contract.get_update_count(PAIR) == 1


def test_update_price_with_all_sources_down_reverts(
    direct_vm, direct_deploy, direct_alice
):
    """If every source fails the update reverts and no state changes."""
    contract = _deploy(direct_vm, direct_deploy, direct_alice)
    contract.set_sources(PAIR, URLS)

    _mock_sources(
        direct_vm,
        bodies=[json.dumps({"price": 100.0})] * 3,
        statuses=[500, 500, 500],
    )
    with direct_vm.expect_revert("[TRANSIENT]"):
        contract.update_price(PAIR)

    assert contract.get_update_count(PAIR) == 0


def test_get_price_for_unknown_pair_reverts(direct_vm, direct_deploy, direct_alice):
    """Reading a price that was never settled reverts; the counter reads zero."""
    contract = _deploy(direct_vm, direct_deploy, direct_alice)

    with direct_vm.expect_revert("No price set"):
        contract.get_price(UNKNOWN_PAIR)

    assert contract.get_update_count(UNKNOWN_PAIR) == 0


def test_update_count_increments_across_updates(
    direct_vm, direct_deploy, direct_alice
):
    """Each successful update bumps the per-pair counter by one."""
    contract = _deploy(direct_vm, direct_deploy, direct_alice)
    contract.set_sources(PAIR, URLS)

    _mock_sources(direct_vm)
    contract.update_price(PAIR)
    contract.update_price(PAIR)

    assert contract.get_update_count(PAIR) == 2
    assert contract.get_price(PAIR) == MEDIAN_PRICE_ATTO


def test_insufficient_usable_sources_reverts_transient(
    direct_vm, direct_deploy, direct_alice
):
    """When only 1 source is available (less than MIN_USABLE_SOURCES=2), reverts with [TRANSIENT]."""
    contract = _deploy(direct_vm, direct_deploy, direct_alice)
    contract.set_sources(PAIR, URLS)

    _mock_sources(
        direct_vm,
        bodies=[
            json.dumps({"price": 100.0}),
            "error",
            "error",
        ],
        statuses=[200, 500, 500],
    )
    with direct_vm.expect_revert("[TRANSIENT]"):
        contract.update_price(PAIR)


def test_canonical_price_bucket_quantization(
    direct_vm, direct_deploy, direct_alice
):
    """Prices with varying precision are quantized to exact canonical 4-decimal bucket."""
    contract = _deploy(direct_vm, direct_deploy, direct_alice)
    contract.set_sources(PAIR, URLS)

    _mock_sources(
        direct_vm,
        bodies=[
            json.dumps({"price": 2500.12345}),
            json.dumps({"price": 2500.12349}),
            json.dumps({"price": 2500.12341}),
        ],
    )
    contract.update_price(PAIR)
    # Median is 2500.12345 -> quantized to 2500.1234
    assert contract.get_price(PAIR) == int(decimal.Decimal("2500.1234") * 10**18)

