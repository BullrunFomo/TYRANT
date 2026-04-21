"""Edge calculation utilities."""
from __future__ import annotations

from pulse.market.scanner import Opportunity


def describe_edge(opp: Opportunity) -> str:
    """Human-readable edge summary."""
    direction = "+" if opp.edge > 0 else ""
    return (
        f"{opp.parsed.city} {opp.parsed.date_str} "
        f"| model={opp.true_prob:.1%} mkt={opp.market_prob:.1%} "
        f"edge={direction}{opp.edge:.1%} → {opp.recommended_outcome}"
    )


def edge_confidence(opp: Opportunity) -> str:
    """Qualitative confidence label."""
    abs_edge = abs(opp.edge)
    if abs_edge >= 0.20:
        return "HIGH"
    elif abs_edge >= 0.12:
        return "MEDIUM"
    return "LOW"
