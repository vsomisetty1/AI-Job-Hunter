"""Claude pricing for cost accounting (USD per million tokens).

Source: Anthropic's published first-party API rates. Cache writes (5-minute
TTL) cost 1.25x input; cache reads are listed per model. Update when prices
change; an unknown model is logged and costed at 0 rather than guessed.
"""

import logging
from decimal import Decimal

logger = logging.getLogger(__name__)

# model -> (input, output, cache_read)
PRICES: dict[str, tuple[str, str, str]] = {
    "claude-fable-5-2": ("8", "40", "0.20"),
    "claude-opus-5-5": ("4", "20", "0.20"),
    "claude-opus-5": ("5", "25", "0.50"),
    "claude-opus-4-8": ("5", "25", "0.50"),
    "claude-sonnet-5-5": ("2", "10", "0.10"),
    "claude-sonnet-5": ("2", "10", "0.20"),
    "claude-haiku-5-5": ("0.10", "0.50", "0.01"),
}
_MILLION = Decimal(1_000_000)
_CACHE_WRITE_MULTIPLIER = Decimal("1.25")


def cost_usd(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> Decimal:
    prices = PRICES.get(model)
    if prices is None:
        logger.warning("no price for model %s; cost recorded as 0", model)
        return Decimal(0)
    p_in, p_out, p_read = (Decimal(p) for p in prices)
    total = (
        input_tokens * p_in
        + output_tokens * p_out
        + cache_read_tokens * p_read
        + cache_write_tokens * p_in * _CACHE_WRITE_MULTIPLIER
    ) / _MILLION
    return total.quantize(Decimal("0.000001"))
