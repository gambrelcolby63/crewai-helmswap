"""CrewAI tools for the HelmSwap public API.

Quote a swap or build an unsigned transaction. The agent's wallet signs and
sends. These tools never hold private keys.
"""

from __future__ import annotations

# Reuse the same function implementations as the LangChain package by vendoring
# a thin wrapper around the shared client. Import locally so this package is
# self-contained.
import json
from typing import Any, Type

from .helmswap_client import (
    HelmswapApi,
    HelmswapApiError,
    SwapParams,
    evm_tx,
    is_live_build_chain,
    min_out_amount,
    net_out_amount,
    parse_chain,
    solana_tx_base64,
)

try:
    from crewai.tools import BaseTool
    from pydantic import BaseModel, Field
except ImportError:
    BaseTool = object  # type: ignore
    class BaseModel:  # type: ignore
        pass
    def Field(*_args, **_kwargs):  # type: ignore
        return None


class HelmswapQuoteInput(BaseModel):
    token_in: str = Field(..., description="Token to spend (address, or ETH, BNB, or SOL)")
    token_out: str = Field(..., description="Token to receive (address, or ETH, BNB, or SOL)")
    amount_in: str = Field(..., description="Integer base units of token_in")
    chain: str = Field(default="base", description="Chain name or id: solana, base, ethereum, bsc, or a numeric chain id")
    slippage_bps: int = Field(default=50, description="Slippage tolerance in basis points (0-1000, default 50)")
    referrer: str | None = Field(default=None, description="Optional payout address. Address only, never a key.")


class HelmswapBuildInput(HelmswapQuoteInput):
    recipient: str = Field(..., description="Wallet that will sign the unsigned transaction (0x or Solana base58)")


def _params(**kwargs) -> SwapParams:
    parsed = parse_chain(kwargs.get("chain") or "base")
    if parsed is None:
        raise HelmswapApiError(f"Unknown chain '{kwargs.get('chain')}'.", 400, "BAD_CHAIN")
    return SwapParams(
        parsed,
        kwargs["token_in"],
        kwargs["token_out"],
        kwargs["amount_in"],
        int(kwargs.get("slippage_bps") or 50),
        kwargs.get("referrer"),
    )


class HelmswapQuoteTool(BaseTool):
    name: str = "helmswap_quote"
    description: str = (
        "Get a HelmSwap quote for a token swap. Returns expected output, minimum output, "
        "and the disclosed fee. Nothing is signed or sent."
    )
    args_schema: Type[BaseModel] = HelmswapQuoteInput

    def _run(self, **kwargs: Any) -> str:
        client = HelmswapApi()
        params = _params(**kwargs)
        quote = client.quote(params)
        fee = quote.get("fee") or (quote.get("quote") or {}).get("fee") or {}
        return json.dumps({
            "ok": True,
            "chain": params.chain,
            "netOutAmount": net_out_amount(quote),
            "minOutAmount": min_out_amount(quote),
            "fee": fee,
            "quoteTicket": quote.get("quoteTicket"),
            "buildable": is_live_build_chain(params.chain),
            "note": "Quote only. The user's wallet must sign any later transaction. HelmSwap never holds keys and never broadcasts.",
        })


class HelmswapBuildTool(BaseTool):
    name: str = "helmswap_build_swap"
    description: str = (
        "Build an unsigned HelmSwap transaction. The recipient wallet signs and sends it. "
        "Never holds private keys. Solana builds need HELMSWAP_API_KEY (a free API key, not a wallet key)."
    )
    args_schema: Type[BaseModel] = HelmswapBuildInput

    def _run(self, **kwargs: Any) -> str:
        recipient = (kwargs.get("recipient") or "").strip()
        if not recipient:
            raise HelmswapApiError("recipient is required to build an unsigned transaction.", 400, "NO_RECIPIENT")
        client = HelmswapApi()
        params = _params(**kwargs)
        quote = client.quote(params)
        built = client.build_tx(params, quote, recipient)
        tx = {"chain": "solana", "transactionBase64": solana_tx_base64(built)} if params.chain == "solana" else evm_tx(built)
        return json.dumps({
            "ok": True,
            "chain": params.chain,
            "recipient": recipient,
            "netOutAmount": net_out_amount(quote),
            "tx": tx,
            "approvals": built.get("approvals") or [],
            "note": "Unsigned transaction. The recipient wallet signs and sends it. HelmSwap never holds keys and never broadcasts.",
        })
