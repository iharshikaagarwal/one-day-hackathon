from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone

from utils.config import ROOT


@dataclass
class UsageEvent:
    agent: str
    input_tokens: int
    output_tokens: int


@dataclass
class CostTracker:
    model: str
    run_id: str
    events: list[UsageEvent] = field(default_factory=list)
    pricing_note: str = ""
    estimated_cost_usd: float = 0.0

    def record(self, agent: str, input_tokens: int, output_tokens: int) -> None:
        self.events.append(
            UsageEvent(agent=agent, input_tokens=int(input_tokens or 0), output_tokens=int(output_tokens or 0))
        )

    def tokens_for(self, agent: str) -> tuple[int, int]:
        incoming = sum(event.input_tokens for event in self.events if event.agent == agent)
        outgoing = sum(event.output_tokens for event in self.events if event.agent == agent)
        return incoming, outgoing

    def totals(self) -> tuple[int, int, int]:
        incoming = sum(event.input_tokens for event in self.events)
        outgoing = sum(event.output_tokens for event in self.events)
        return incoming, outgoing, incoming + outgoing

    def estimate(self) -> float:
        pricing = json.loads((ROOT / "data" / "model_pricing.json").read_text(encoding="utf-8"))
        rates = pricing["models"].get(self.model, pricing["default"])
        if self.model in pricing["models"]:
            self.pricing_note = pricing["note"]
        else:
            self.pricing_note = (
                pricing["note"]
                + " This model is not listed, so default rates were used."
            )
        incoming, outgoing, _ = self.totals()
        cost = (incoming * float(rates["input"]) + outgoing * float(rates["output"])) / 1_000_000
        self.estimated_cost_usd = round(cost, 6)
        return self.estimated_cost_usd

    def summary_dict(self) -> dict:
        incoming, outgoing, total = self.totals()
        self.estimate()
        return {
            "model": self.model or "unconfigured",
            "input_tokens": incoming,
            "output_tokens": outgoing,
            "total_tokens": total,
            "estimated_cost_usd": self.estimated_cost_usd,
            "currency": "USD",
            "label": "Estimated API cost",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "pricing_note": self.pricing_note,
        }
