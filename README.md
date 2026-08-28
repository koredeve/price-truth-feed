PriceTruthFeed — manipulation-resistant price feed for GenLayer
================================================================

PriceTruthFeed lets a contract owner configure at least three public HTTP
price sources per trading pair (e.g. `ETH/USD`). When anyone triggers an
update, the transaction leader fetches every configured source live,
defensively parses each JSON body (`{"price": <number>}`), and stores the
median price as an atto-denominated `u256` (`value * 10**18`). Because the
value comes from third-party websites, correctness cannot be taken from the
leader alone: an independent validator re-fetches all sources itself and only
accepts the leader's result when both medians agree.

Architecture
------------

- **User action**: owner calls `set_sources(pair, urls)` once per pair; anyone
  may then call `update_price(pair)` to refresh the on-chain price.
- **Evidence source**: >= 3 operator-chosen URLs that answer HTTP 200 with
  JSON `{"price": <number>}`. Non-200 responses and malformed bodies are
  skipped; fewer than two usable sources aborts the update.
- **Nondet call**: `update_price` runs a custom nondet resolution via
  `gl.vm.run_nondet_unsafe(leader_fn, validator_fn)`. The leader fetches all
  sources, computes the median, and quantizes it to an exact 4-decimal canonical
  price bucket (`{"bucket": str(dq), "sources": len(values)}`).
- **Equivalence principle**: the validator independently re-executes
  `leader_fn` (its own refetch of every source, median computation, and canonical
  bucketing) and accepts only when `leader_data["bucket"] == fresh["bucket"]`.
  If the leader errored, the canonical `_handle_leader_error` rules decide:
  transient failures on both sides agree, deterministic business errors must
  match exactly. Leader output is never trusted without this exact consensus check.
- **Settlement effect**: on exact bucket agreement the canonical price is persisted to
  `prices[pair]`, `update_count[pair]` is incremented, and both are readable
  via views. On disagreement the node rejects the proposal; nothing settles.
- **Appeal path**: GenLayer Optimistic Democracy provides
  leader-proposes / validator-check natively, including an appeal window in
  which stakers can challenge a settled result before it becomes final.

Quickstart
----------

Requires Python 3.14.

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Lint the contract
genvm-lint check contracts/PriceTruthFeed.py --json

# Run direct-mode tests (web/LLM mocked)
pytest tests/direct/ -v
```

Integration tests target StudioNet via `gltest.config.yaml`.

Interface
---------

| Method | Type | Notes |
| --- | --- | --- |
| `owner()` | view | Returns the deployer-configured owner address. |
| `set_sources(pair, urls)` | write | Owner-only; requires at least 3 URLs. Replaces any previous list for the pair. |
| `update_price(pair)` | write | Sources must exist. Fetches all URLs, skips non-200/malformed responses, needs >= 2 usable, stores the canonical price bucket in atto u256 after exact validator consensus. |
| `get_price(pair)` | view | Atto-median price; reverts if never settled. |
| `get_update_count(pair)` | view | Number of successful updates; zero before the first one. |

StudioNet note: transactions on StudioNet are gasless — holding 0 GEN is fine.
