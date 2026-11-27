from __future__ import annotations

import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from crewai_helmswap.helmswap_client import HelmswapApi
from crewai_helmswap import tools as tools_mod


SAMPLE_QUOTE = {
    "ok": True,
    "quoteTicket": {"sig": "ticket", "quotedOutNet": "149250000"},
    "quote": {"netOutAmount": "149250000", "minNetOutAmount": "148500000", "fee": {"disclosed": True, "feeBps": 25}},
    "fee": {"disclosed": True, "feeBps": 25},
}

SAMPLE_BUILD = {"ok": True, "tx": {"to": "0xrouter", "data": "0xabc", "value": "0x0", "chainId": 1}, "approvals": []}


class FakeResponse(io.BytesIO):
    def __init__(self, payload, status=200):
        super().__init__(json.dumps(payload).encode())
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_quote_and_build_tools(monkeypatch):
    def opener(req):
        if req.get_method() == "GET":
            return FakeResponse(SAMPLE_QUOTE)
        return FakeResponse(SAMPLE_BUILD)

    monkeypatch.setattr(tools_mod, "HelmswapApi", lambda: HelmswapApi(base_url="https://helmswap.com", opener=opener))
    quoted = json.loads(tools_mod.HelmswapQuoteTool()._run(
        token_in="ETH",
        token_out="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        amount_in="10000000000000000",
        chain="ethereum",
    ))
    assert quoted["netOutAmount"] == "149250000"
    built = json.loads(tools_mod.HelmswapBuildTool()._run(
        token_in="ETH",
        token_out="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
        amount_in="10000000000000000",
        chain="ethereum",
        recipient="0x1111111111111111111111111111111111111111",
    ))
    assert built["tx"]["to"] == "0xrouter"
