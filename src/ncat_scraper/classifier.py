"""Classifier for NCAT Appeal Panel decisions.

Classifies decisions based on:
1. Decision type: final (appeal allowed/dismissed) vs interlocutory (costs, stays, etc)
2. Grounds of appeal (for final decisions)
3. Outcome (for final decisions)
4. Successful grounds (for allowed appeals)
"""

import logging
import re
from typing import Literal

from .models import Decision, ScrapedDecisionData

logger = logging.getLogger(__name__)


# Patterns indicating interlocutory decisions
INTERLOCUTORY_PATTERNS = [
    r"\bcosts?\b.*\b(application|order|assessment)\b",
    r"\bstay\b.*\b(application|order|granted|refused)\b",
    r"\bextension\s+of\s+time\b",
    r"\bleave\s+to\s+appeal\b",
    r"\badjournment\b",
    r"\binterlocutory\b",
    r"\bprocedural\b.*\border\b",
    r"\bamendment\b.*\b(application|order)\b",
    r"\bjoinder\b",
    r"\bdismissed\s+as\s+incompetent\b",
    r"\bstruck\s+out\b",
]

# Patterns indicating final appeal outcome
APPEAL_ALLOWED_PATTERNS = [
    r"appeal\s+(?:is\s+)?allowed",
    r"the\s+appeal\s+(?:is\s+)?allowed",
    r"appeals?\s+(?:are\s+)?allowed",
    r"allow\s+the\s+appeal",
]

APPEAL_DISMISSED_PATTERNS = [
    r"appeal\s+(?:is\s+)?dismissed",
    r"the\s+appeal\s+(?:is\s+)?dismissed",
    r"appeals?\s+(?:are\s+)?dismissed",
    r"dismiss\s+the\s+appeal",
]

# Common grounds of appeal in NCAT matters
# These are based on s 80(2) of the Civil and Administrative Tribunal Act 2013 (NSW)
GROUND_PATTERNS = {
    "error_of_law": [
        r"error\s+of\s+law",
        r"question\s+of\s+law",
        r"misconstrued\s+the\s+law",
        r"misapplied\s+the\s+law",
        r"wrong\s+in\s+law",
    ],
    "denial_of_procedural_fairness": [
        r"procedural\s+fairness",
        r"natural\s+justice",
        r"denial\s+of\s+(?:procedural\s+)?fairness",
        r"denied\s+(?:procedural\s+)?fairness",
        r"breach\s+of\s+(?:procedural\s+)?fairness",
        r"not\s+(?:afforded|given)\s+(?:an?\s+)?(?:adequate\s+)?opportunity",
    ],
    "jurisdictional_error": [
        r"jurisdictional\s+error",
        r"exceeded\s+(?:its\s+)?jurisdiction",
        r"lack\s+of\s+jurisdiction",
        r"without\s+jurisdiction",
    ],
    "evidence_and_findings": [
        r"no\s+evidence",
        r"against\s+the\s+evidence",
        r"weight\s+of\s+(?:the\s+)?evidence",
        r"insufficient\s+evidence",
        r"finding\s+(?:was\s+)?not\s+(?:open|available)",
        r"finding\s+(?:was\s+)?unsupported",
        r"illogical\s+or\s+irrational",
        r"Wednesbury\s+unreasonable",
    ],
    "failure_to_give_reasons": [
        r"fail(?:ed|ure)\s+to\s+(?:give|provide)\s+(?:adequate\s+)?reasons",
        r"inadequate\s+reasons",
        r"insufficient\s+reasons",
    ],
    "irrelevant_considerations": [
        r"irrelevant\s+consideration",
        r"relevant\s+consideration",
        r"took\s+into\s+account\s+(?:an?\s+)?irrelevant",
        r"fail(?:ed|ure)\s+to\s+(?:take\s+into\s+account|consider)",
    ],
    "apprehended_bias": [
        r"apprehended\s+bias",
        r"actual\s+bias",
        r"reasonable\s+apprehension\s+of\s+bias",
    ],
    "fresh_evidence": [
        r"fresh\s+evidence",
        r"new\s+evidence",
    ],
}


def classify_decision(scraped_data: ScrapedDecisionData) -> Decision:
    """Classify a scraped decision.

    Analyzes the decision text to determine:
    - Whether it is final or interlocutory
    - For final decisions: grounds of appeal, outcome, successful grounds

    Args:
        scraped_data: Raw scraped data from decision page

    Returns:
        Classified Decision object
    """
    text = scraped_data.body_text.lower()
    catchwords = scraped_data.catchwords.lower()
    combined_text = f"{catchwords}\n{text}"

    # Determine if interlocutory
    is_interlocutory = _is_interlocutory(combined_text, catchwords)

    if is_interlocutory:
        return Decision(
            url=scraped_data.url,
            medium_neutral_citation=scraped_data.medium_neutral_citation,
            year=scraped_data.year,
            decision_makers=scraped_data.decision_makers,
            decision_type="interlocutory",
            grounds_of_appeal=[],
            outcome=None,
            successful_grounds=[],
        )

    # Final decision - extract grounds and outcome
    grounds = _extract_grounds(combined_text)
    outcome = _determine_outcome(text)
    successful_grounds = []

    if outcome == "allowed":
        successful_grounds = _extract_successful_grounds(text, grounds)

    return Decision(
        url=scraped_data.url,
        medium_neutral_citation=scraped_data.medium_neutral_citation,
        year=scraped_data.year,
        decision_makers=scraped_data.decision_makers,
        decision_type="final",
        grounds_of_appeal=grounds,
        outcome=outcome,
        successful_grounds=successful_grounds,
    )


def _is_interlocutory(text: str, catchwords: str) -> bool:
    """Determine if decision is interlocutory based on content.

    Checks for patterns indicating procedural/preliminary matters
    rather than final disposition of the appeal.
    """
    # Check catchwords first - strong signal
    for pattern in INTERLOCUTORY_PATTERNS:
        if re.search(pattern, catchwords, re.IGNORECASE):
            logger.debug(f"Interlocutory: matched '{pattern}' in catchwords")
            return True

    # If text contains clear final appeal language, not interlocutory
    has_allowed = any(re.search(p, text, re.IGNORECASE) for p in APPEAL_ALLOWED_PATTERNS)
    has_dismissed = any(re.search(p, text, re.IGNORECASE) for p in APPEAL_DISMISSED_PATTERNS)

    if has_allowed or has_dismissed:
        # Check if this is just about costs/stay in an otherwise final decision
        # by looking at orders section
        orders_match = re.search(r"orders?\s*[:\n](.*?)(?:\n\n|$)", text, re.IGNORECASE | re.DOTALL)
        if orders_match:
            orders_text = orders_match.group(1).lower()
            # If orders only mention costs or procedural matters, still consider it final
            # as long as appeal allowed/dismissed is present
            return False

    # Check body for interlocutory patterns if no clear final outcome
    if not has_allowed and not has_dismissed:
        for pattern in INTERLOCUTORY_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True

    return False


def _extract_grounds(text: str) -> list[str]:
    """Extract grounds of appeal from decision text.

    Returns standardized ground names based on patterns found.
    """
    found_grounds = []

    for ground_name, patterns in GROUND_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                if ground_name not in found_grounds:
                    found_grounds.append(ground_name)
                break

    return found_grounds


def _determine_outcome(text: str) -> Literal["allowed", "dismissed"] | None:
    """Determine appeal outcome from decision text.

    Looks for explicit outcome statements, typically in orders section.
    """
    # Look in orders section first (more reliable)
    orders_match = re.search(
        r"(?:orders?|decision)\s*[:\n](.*?)(?:\n\n|\Z)",
        text,
        re.IGNORECASE | re.DOTALL
    )

    search_text = orders_match.group(1) if orders_match else text[-2000:]

    # Check for allowed
    for pattern in APPEAL_ALLOWED_PATTERNS:
        if re.search(pattern, search_text, re.IGNORECASE):
            return "allowed"

    # Check for dismissed
    for pattern in APPEAL_DISMISSED_PATTERNS:
        if re.search(pattern, search_text, re.IGNORECASE):
            return "dismissed"

    # Fallback: search full text
    for pattern in APPEAL_ALLOWED_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return "allowed"

    for pattern in APPEAL_DISMISSED_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return "dismissed"

    logger.warning("Could not determine appeal outcome")
    return None


def _extract_successful_grounds(text: str, all_grounds: list[str]) -> list[str]:
    """Extract which grounds were successful in an allowed appeal.

    This is challenging as decisions don't always explicitly state which
    grounds succeeded. We look for patterns like:
    - "the ground of X is made out"
    - "we accept that there was X"
    - "the Tribunal erred in X"

    Falls back to returning all grounds if we can't determine specifics.
    """
    successful = []

    # Patterns indicating a ground was upheld
    success_patterns = [
        r"(?:ground|complaint)\s+(?:of\s+)?{ground}.*(?:is\s+)?(?:made\s+out|established|upheld|succeeds)",
        r"(?:we|the\s+panel)\s+(?:find|accept|conclude).*{ground}",
        r"there\s+was\s+(?:a\s+|an\s+)?{ground}",
        r"{ground}.*(?:is|was)\s+(?:established|demonstrated|proven)",
    ]

    ground_text_map = {
        "error_of_law": "error of law",
        "denial_of_procedural_fairness": "(?:denial of )?procedural fairness|natural justice",
        "jurisdictional_error": "jurisdictional error",
        "evidence_and_findings": "(?:no|insufficient) evidence|finding.*not open",
        "failure_to_give_reasons": "fail.*reasons|inadequate reasons",
        "irrelevant_considerations": "(?:ir)?relevant consideration",
        "apprehended_bias": "(?:apprehended )?bias",
        "fresh_evidence": "fresh evidence|new evidence",
    }

    for ground in all_grounds:
        ground_text = ground_text_map.get(ground, ground.replace("_", " "))
        for pattern_template in success_patterns:
            pattern = pattern_template.format(ground=ground_text)
            if re.search(pattern, text, re.IGNORECASE):
                if ground not in successful:
                    successful.append(ground)
                break

    # If appeal allowed but couldn't identify specific grounds, return all
    # (better to over-report than miss)
    if not successful and all_grounds:
        logger.debug("Could not identify specific successful grounds, returning all")
        return all_grounds

    return successful
