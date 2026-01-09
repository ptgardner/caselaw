"""Data models for NCAT Appeal Panel decisions."""

from dataclasses import dataclass, field, asdict
from typing import Literal
import json


DecisionType = Literal["final", "interlocutory"]
Outcome = Literal["allowed", "dismissed"] | None


@dataclass
class Decision:
    """Represents a single NCAT Appeal Panel decision.

    Attributes:
        url: Full URL to the decision on caselaw.nsw.gov.au
        medium_neutral_citation: Citation in format "Party v Party [YYYY] NSWCATAP #"
        year: Year of the decision
        decision_makers: List of tribunal member names who made the decision
        decision_type: "final" (appeal dismissed/allowed) or "interlocutory" (costs, stays, etc)
        grounds_of_appeal: List of grounds raised by appellant (empty for interlocutory)
        outcome: "allowed" or "dismissed" for final decisions, None for interlocutory
        successful_grounds: Grounds on which appeal succeeded (empty unless outcome is "allowed")
    """
    url: str
    medium_neutral_citation: str
    year: int
    decision_makers: list[str]
    decision_type: DecisionType
    grounds_of_appeal: list[str] = field(default_factory=list)
    outcome: Outcome = None
    successful_grounds: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert decision to dictionary for JSON serialization."""
        return asdict(self)


@dataclass
class ScrapedDecisionData:
    """Raw data scraped from a decision page before classification.

    Attributes:
        url: Full URL to the decision
        medium_neutral_citation: Citation string
        year: Year extracted from citation
        decision_makers: List of member names
        body_text: Full text of the decision body
        catchwords: Catchwords/keywords if present
    """
    url: str
    medium_neutral_citation: str
    year: int
    decision_makers: list[str]
    body_text: str
    catchwords: str = ""


def decisions_to_json(decisions: list[Decision], indent: int = 2) -> str:
    """Convert list of decisions to JSON string."""
    return json.dumps(
        {"decisions": [d.to_dict() for d in decisions]},
        indent=indent,
        ensure_ascii=False
    )
