# { "Depends": "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6" }

from genlayer import *
import json
import decimal


ERROR_EXPECTED = "[EXPECTED]"
ERROR_EXTERNAL = "[EXTERNAL]"
ERROR_TRANSIENT = "[TRANSIENT]"
ERROR_LLM = "[LLM_ERROR]"

PRICE_SCALE = 1000000000000000000
AGREEMENT_NUMERATOR = 5
AGREEMENT_DENOMINATOR = 1000
MIN_SOURCES = 3
MIN_USABLE_SOURCES = 2


def _handle_leader_error(leaders_res, leader_fn) -> bool:
	leader_msg = leaders_res.message if hasattr(leaders_res, "message") else ""
	try:
		leader_fn()
		return False
	except gl.vm.UserError as e:
		validator_msg = e.message if hasattr(e, "message") else str(e)
		if validator_msg.startswith(ERROR_EXPECTED) or validator_msg.startswith(ERROR_EXTERNAL):
			return validator_msg == leader_msg
		if validator_msg.startswith(ERROR_TRANSIENT) and leader_msg.startswith(ERROR_TRANSIENT):
			return True
		return False
	except Exception:
		return False


class PriceTruthFeed(gl.Contract):
	owner_addr: Address
	sources: TreeMap[str, DynArray[str]]
	prices: TreeMap[str, u256]
	update_count: TreeMap[str, u256]

	def __init__(self) -> None:
		sender = gl.message.sender_address
		self.owner_addr = sender if isinstance(sender, Address) else Address(sender)

	def _require_owner(self) -> None:
		if gl.message.sender_address != self.owner_addr:
			raise gl.vm.UserError(f"{ERROR_EXPECTED} Only owner")

	@gl.public.view
	def owner(self) -> Address:
		return self.owner_addr

	@gl.public.write
	def set_sources(self, pair: str, urls: DynArray[str]) -> None:
		self._require_owner()
		if len(urls) < MIN_SOURCES:
			raise gl.vm.UserError(f"{ERROR_EXPECTED} At least three source URLs are required")
		self.sources[pair] = []
		bucket = self.sources[pair]
		for i in range(len(urls)):
			bucket.append(str(urls[i]))

	@gl.public.write
	def update_price(self, pair: str) -> None:
		stored = self.sources.get(pair)
		if stored is None:
			raise gl.vm.UserError(f"{ERROR_EXPECTED} Unknown pair: no sources configured")
		urls = []
		for i in range(len(stored)):
			urls.append(str(stored[i]))

		def leader_fn() -> dict:
			values = []
			for url in urls:
				res = gl.nondet.web.get(url)
				if res.status != 200:
					continue
				raw_body = res.body
				if raw_body is None:
					continue
				try:
					parsed = json.loads(bytes(raw_body).decode("utf-8"))
				except Exception:
					continue
				if not isinstance(parsed, dict) or "price" not in parsed:
					continue
				try:
					price_value = float(parsed["price"])
				except Exception:
					continue
				if price_value != price_value or price_value in (
					float("inf"),
					float("-inf"),
				):
					continue
				values.append(price_value)
			if len(values) < MIN_USABLE_SOURCES:
				raise gl.vm.UserError(
					f"{ERROR_TRANSIENT} insufficient live sources for {pair}"
				)
			values.sort()
			median = values[len(values) // 2]
			# Canonical price bucket: quantize the median to exactly 4 decimals.
			# Validators recompute this identically — agreement is EXACT on the
			# normalized value, so one deterministic number becomes on-chain truth.
			dq = decimal.Decimal(str(median)).quantize(decimal.Decimal("0.0001"))
			return {"bucket": str(dq), "sources": len(values)}

		def validator_fn(leaders_res: gl.vm.Result) -> bool:
			if not isinstance(leaders_res, gl.vm.Return):
				return _handle_leader_error(leaders_res, leader_fn)
			leader_data = leaders_res.calldata
			fresh = leader_fn()
			return (
				str(leader_data.get("bucket", "")) == str(fresh.get("bucket", ""))
				and str(fresh.get("bucket", "")) != ""
			)

		result = gl.vm.run_nondet_unsafe(leader_fn, validator_fn)

		bucket_str = str(result["bucket"])
		price_stored = u256(int(decimal.Decimal(bucket_str) * decimal.Decimal("1000000000000000000")))
		self.prices[pair] = price_stored
		self.update_count[pair] = self.update_count.get(pair, u256(0)) + u256(1)

	@gl.public.view
	def get_price(self, pair: str) -> u256:
		price = self.prices.get(pair)
		if price is None:
			raise gl.vm.UserError(f"{ERROR_EXPECTED} No price set for pair")
		return price

	@gl.public.view
	def get_update_count(self, pair: str) -> u256:
		return self.update_count.get(pair, u256(0))
