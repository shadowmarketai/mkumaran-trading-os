from mcp_server import prompts
from mcp_server.sector_picker import NSE_SECTOR_MAP


def test_all_10_prompts_defined():
    prompt_names = [
        "GOLDMAN_SCREEN_PROMPT",
        "MORGAN_STANLEY_DCF_PROMPT",
        "BRIDGEWATER_RISK_PROMPT",
        "JPMORGAN_EARNINGS_PROMPT",
        "BLACKROCK_PORTFOLIO_PROMPT",
        "CITADEL_TECHNICAL_PROMPT",
        "HARVARD_DIVIDEND_PROMPT",
        "BAIN_COMPETITIVE_PROMPT",
        "RENAISSANCE_PATTERN_PROMPT",
        "MCKINSEY_MACRO_PROMPT",
    ]
    for name in prompt_names:
        val = getattr(prompts, name, None)
        assert val is not None, f"Missing prompt: {name}"
        assert isinstance(val, str), f"Prompt {name} is not a string"
        assert len(val) > 50, f"Prompt {name} is too short"


def test_sector_map_size():
    assert len(NSE_SECTOR_MAP) >= 25


def test_sector_picker_get_peers():
    result = NSE_SECTOR_MAP.get("NSE:TATASTEEL")
    assert result is not None
    assert "sector" in result
    assert "peers" in result
    assert len(result["peers"]) >= 3


def test_sector_picker_unknown_ticker():
    result = NSE_SECTOR_MAP.get("NSE:UNKNOWN123")
    assert result is None
