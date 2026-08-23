from gltest import get_contract_factory
from gltest.assertions import tx_execution_succeeded


def test_deploy_smoke():
    factory = get_contract_factory("PriceTruthFeed")
    contract = factory.deploy(args=[])
    result = contract.owner(args=[]).call()
    assert result is not None
    assert tx_execution_succeeded()
