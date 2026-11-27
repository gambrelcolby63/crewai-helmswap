# crewai-helmswap

CrewAI tools for [HelmSwap](https://helmswap.com/developers). They quote a swap and return an **unsigned** transaction. The agent's own wallet signs and sends it. The tools never hold private keys.

Do not publish or run `crewai tool publish` until helmswap.com is back up and Colby has approved the submit.

## Usage (after publish)

```python
from crewai_helmswap import HelmswapQuoteTool, HelmswapBuildTool

tools = [HelmswapQuoteTool(), HelmswapBuildTool()]
```

Set `HELMSWAP_API_KEY` (free key from https://helmswap.com/developers, never a wallet key) for Solana builds. `HELMSWAP_BASE_URL` is optional.

`amount_in` is integer base units.

## License

MIT © Summit Private Credit LLC
