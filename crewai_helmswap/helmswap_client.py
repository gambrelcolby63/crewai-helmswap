"""HelmSwap public v1 HTTP client.

Verified against the 26 Nov 2026 audit fix-tree:
GET /api/v1/quote and POST /api/v1/build-tx.

Returns quotes and unsigned transactions. This client never holds keys,
never signs, and never broadcasts.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Mapping, MutableMapping

DEFAULT_BASE_URL = "https://helmswap.com"
KEY_DOCS = "https://helmswap.com/developers"
WSOL = "So11111111111111111111111111111111111111112"
LIVE_EVM_CHAIN_IDS = (8453, 56, 1, 4663, 57073, 999, 99901, 5042)
QUOTE_ONLY_CHAIN_IDS = (42161, 137)

CHAIN_ALIASES: dict[str, int | str] = {
    "solana": "solana",
    "sol": "solana",
    "base": 8453,
    "8453": 8453,
    "bnb": 56,
    "bsc": 56,
    "bnbchain": 56,
    "56": 56,
    "eth": 1,
    "ethereum": 1,
    "mainnet": 1,
    "1": 1,
    "robinhood": 4663,
    "4663": 4663,
    "ink": 57073,
    "57073": 57073,
    "hyperevm": 999,
    "999": 999,
    "elysium": 99901,
    "99901": 99901,
    "arc": 5042,
    "5042": 5042,
    "arbitrum": 42161,
    "42161": 42161,
    "polygon": 137,
    "137": 137,
}


class HelmswapApiError(Exception):
    def __init__(self, message: str, status: int, code: str | None = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body


def parse_chain(raw: str | int | None) -> int | str | None:
    if raw is None or raw == "":
        return None
    if isinstance(raw, int):
        return raw
    trimmed = str(raw).strip()
    if trimmed.isdigit():
        return int(trimmed)
    return CHAIN_ALIASES.get(trimmed.lower().replace(" ", ""))


def is_live_build_chain(chain: int | str) -> bool:
    return chain == "solana" or chain in LIVE_EVM_CHAIN_IDS


def to_base_units(amount: str | int | float, decimals: int) -> str:
    trimmed = str(amount).strip()
    if not trimmed or trimmed.startswith("-"):
        raise ValueError("amount must be greater than zero")
    if "." in trimmed:
        whole, frac = trimmed.split(".", 1)
    else:
        whole, frac = trimmed, ""
    if not whole.isdigit() or (frac and not frac.isdigit()):
        raise ValueError("amount must be a positive number")
    frac_padded = (frac + ("0" * decimals))[:decimals]
    raw = (whole + frac_padded).lstrip("0") or "0"
    if raw == "0":
        raise ValueError("amount must be greater than zero")
    return raw


def from_base_units(raw: str, decimals: int) -> float:
    if not str(raw).isdigit():
        raise ValueError("base units must be a non-negative integer string")
    padded = str(raw).zfill(decimals + 1)
    whole, frac = padded[:-decimals], padded[-decimals:]
    return float(f"{whole}.{frac}")


def native_or_mint(token: str, chain: int | str) -> str:
    token = token.strip()
    if chain == "solana" and token.upper() == "SOL":
        return WSOL
    return token


@dataclass
class SwapParams:
    chain: int | str
    token_in: str
    token_out: str
    amount_in: str
    slippage_bps: int | None = None
    referrer: str | None = None


def quote_query(params: SwapParams) -> dict[str, str]:
    q: dict[str, str]
    if params.chain == "solana":
        q = {
            "chain": "solana",
            "inputMint": native_or_mint(params.token_in, "solana"),
            "outputMint": native_or_mint(params.token_out, "solana"),
            "amount": params.amount_in,
        }
    else:
        q = {
            "chainId": str(params.chain),
            "tokenIn": params.token_in,
            "tokenOut": params.token_out,
            "amountIn": params.amount_in,
        }
    if params.slippage_bps is not None:
        q["slippageBps"] = str(params.slippage_bps)
    if params.referrer:
        q["referrer"] = params.referrer
    return q


def build_body(params: SwapParams, quote: Mapping[str, Any], recipient: str) -> dict[str, Any]:
    ticket = quote.get("quoteTicket")
    if not isinstance(ticket, Mapping):
        raise HelmswapApiError(
            "quote.quoteTicket is missing; call quote() first and pass the result unchanged.",
            400,
            "NO_TICKET",
        )
    if params.chain == "solana":
        q = quote_query(params)
        body: dict[str, Any] = {
            "chain": "solana",
            "inputMint": q["inputMint"],
            "outputMint": q["outputMint"],
            "amount": q["amount"],
            "recipient": recipient,
            "quoteTicket": ticket,
        }
    else:
        body = {
            "chainId": params.chain,
            "tokenIn": params.token_in,
            "tokenOut": params.token_out,
            "amountIn": params.amount_in,
            "recipient": recipient,
            "quoteTicket": ticket,
        }
    if params.slippage_bps is not None:
        body["slippageBps"] = params.slippage_bps
    if params.referrer:
        body["referrer"] = params.referrer
    return body


def net_out_amount(quote: Mapping[str, Any]) -> str:
    inner = quote.get("quote") if isinstance(quote.get("quote"), Mapping) else {}
    ticket = quote.get("quoteTicket") if isinstance(quote.get("quoteTicket"), Mapping) else {}
    raw = inner.get("netOutAmount") or quote.get("netOutAmount") or ticket.get("quotedOutNet")
    if raw is None:
        raise HelmswapApiError("HelmSwap quote had no netOutAmount.", 502, "NO_NET_OUT", quote)
    return str(raw)


def min_out_amount(quote: Mapping[str, Any]) -> str:
    inner = quote.get("quote") if isinstance(quote.get("quote"), Mapping) else {}
    return str(inner.get("minOutNet") or inner.get("minNetOutAmount") or net_out_amount(quote))


def evm_tx(built: Mapping[str, Any]) -> dict[str, Any]:
    tx = built.get("tx")
    if not isinstance(tx, Mapping) or not tx.get("to") or not tx.get("data"):
        raise HelmswapApiError("HelmSwap build-tx response had no EVM tx.", 502, "NO_TX", built)
    return dict(tx)


def solana_tx_base64(built: Mapping[str, Any]) -> str:
    tx = built.get("tx")
    if isinstance(tx, Mapping) and isinstance(tx.get("transactionBase64"), str):
        return tx["transactionBase64"]
    raise HelmswapApiError("HelmSwap build-tx response had no Solana transaction.", 502, "NO_TX", built)


class HelmswapApi:
    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        opener: Callable[..., Any] | None = None,
    ):
        self.base_url = (base_url or os.environ.get("HELMSWAP_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key if api_key is not None else os.environ.get("HELMSWAP_API_KEY")
        self._opener = opener or urllib.request.urlopen

    @property
    def has_api_key(self) -> bool:
        return bool(self.api_key)

    def quote(self, params: SwapParams) -> dict[str, Any]:
        query = urllib.parse.urlencode(quote_query(params))
        return self._request("GET", f"/api/v1/quote?{query}")

    def build_tx(self, params: SwapParams, quote: Mapping[str, Any], recipient: str) -> dict[str, Any]:
        if params.chain == "solana" and not self.api_key:
            raise HelmswapApiError(
                "A free HelmSwap API key is required to build Solana transactions. Create one at https://helmswap.com/developers.",
                401,
                "API_KEY_REQUIRED",
            )
        if not is_live_build_chain(params.chain):
            raise HelmswapApiError(
                f"build-tx is not available on chain {params.chain} (quote-only).",
                503,
                "FEE_ROUTER_NOT_CONFIGURED",
            )
        return self._request("POST", "/api/v1/build-tx", build_body(params, quote, recipient))

    def _request(self, method: str, path: str, body: Mapping[str, Any] | None = None) -> dict[str, Any]:
        headers: dict[str, str] = {"Accept": "application/json"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        if self.api_key:
            headers["X-Helm-Key"] = self.api_key
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with self._opener(req) as resp:
                raw = resp.read()
                status = getattr(resp, "status", 200)
        except urllib.error.HTTPError as err:
            raw = err.read()
            status = err.code
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except json.JSONDecodeError as err:
            raise HelmswapApiError(f"HelmSwap returned a non-JSON response ({status})", status) from err
        if not isinstance(payload, dict):
            raise HelmswapApiError(f"HelmSwap returned a non-object response ({status})", status, body=payload)
        if status >= 400 or payload.get("ok") is False:
            raise HelmswapApiError(
                payload.get("error") if isinstance(payload.get("error"), str) else f"HelmSwap request failed ({status})",
                status,
                payload.get("code") if isinstance(payload.get("code"), str) else None,
                payload,
            )
        return payload
