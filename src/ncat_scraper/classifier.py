"""Classifier for NCAT Appeal Panel decisions.

Classifies decisions based on:
1. Decision type: final (appeal allowed/dismissed) vs interlocutory (costs, stays, etc)
2. Grounds of appeal - granular taxonomy based on Prendergast and subsequent authorities
3. Outcome (for final decisions)
4. Successful grounds (for allowed appeals)

Taxonomy based on:
- Prendergast v Western Murray Irrigation Ltd [2014] NSWCATAP 69 at [13]
- Al-Miahi [2001] FCA 744 at [34] (inferences)
- Bianco Walling [2020] FCAFC 50 at [66] (statutory/contract construction)
- Dranichnikov [2003] HCA 26; Alexandria Landfill [2020] NSWCA 165 (failure to address submissions)
- Hope v Bathurst City Council (1980) 144 CLR 1 (facts satisfying statute)
- Peko-Wallsend (1986) 162 CLR 24 (mandatory/prohibited considerations)
- Hossain [2018] HCA 34 at [24] (jurisdictional error)
- Pozzolanic (1993) 43 FCR 280 (law/fact distinction)
"""

import logging
import re
from dataclasses import dataclass
from typing import Literal

from .models import Decision, ScrapedDecisionData

logger = logging.getLogger(__name__)


# =============================================================================
# GROUND TAXONOMY
# =============================================================================
# Hierarchical structure: category -> sub-category -> patterns
# Categories are not closed per the authorities.

@dataclass
class GroundDefinition:
    """Definition of a ground of appeal with detection patterns."""
    code: str
    category: str
    description: str
    patterns: list[str]
    authority: str = ""


GROUNDS: list[GroundDefinition] = [
    # -------------------------------------------------------------------------
    # PROCEDURAL FAIRNESS / NATURAL JUSTICE
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="pf_no_hearing",
        category="procedural_fairness",
        description="Denial of opportunity to be heard",
        patterns=[
            r"denied?\s+(?:the\s+)?opportunity\s+to\s+(?:be\s+)?heard",
            r"not\s+(?:given|afforded)\s+(?:an?\s+)?(?:adequate\s+)?opportunity\s+to\s+(?:be\s+)?heard",
            r"denied?\s+a\s+hearing",
            r"no\s+opportunity\s+to\s+(?:present|make)\s+submissions",
        ],
        authority="Fair hearing rule",
    ),
    GroundDefinition(
        code="pf_no_notice",
        category="procedural_fairness",
        description="No notice of case to answer or issues to be decided",
        patterns=[
            r"no\s+notice\s+of\s+(?:the\s+)?(?:case|issues?|matters?)",
            r"not\s+(?:given|provided)\s+(?:adequate\s+)?notice",
            r"without\s+notice",
            r"unaware\s+of\s+(?:the\s+)?(?:case|issues?)",
        ],
        authority="Fair hearing rule",
    ),
    GroundDefinition(
        code="pf_new_issue",
        category="procedural_fairness",
        description="Decision based on issue not raised with parties",
        patterns=[
            r"issue\s+not\s+raised",
            r"matter\s+not\s+(?:raised|put)\s+to",
            r"decided\s+on\s+(?:a\s+)?basis\s+not\s+(?:raised|put)",
            r"new\s+(?:issue|matter|point)\s+(?:not\s+)?raised",
            r"without\s+(?:giving|affording)\s+(?:the\s+)?(?:parties?\s+)?(?:an?\s+)?opportunity\s+to\s+(?:address|respond)",
        ],
        authority="Fair hearing rule",
    ),
    GroundDefinition(
        code="pf_no_cross_examination",
        category="procedural_fairness",
        description="Denied opportunity to test evidence",
        patterns=[
            r"denied?\s+(?:the\s+)?opportunity\s+to\s+cross[- ]?examin",
            r"not\s+(?:given|afforded|permitted)\s+(?:the\s+)?(?:opportunity\s+)?to\s+cross[- ]?examin",
            r"unable\s+to\s+(?:test|challenge)\s+(?:the\s+)?evidence",
        ],
        authority="Fair hearing rule",
    ),
    GroundDefinition(
        code="pf_failure_to_address_submissions",
        category="procedural_fairness",
        description="Failed to respond to substantial, clearly articulated arguments",
        patterns=[
            r"fail(?:ed|ure)\s+to\s+(?:address|consider|deal\s+with|respond\s+to)\s+(?:the\s+)?(?:substantial\s+)?(?:submission|argument)",
            r"did\s+not\s+(?:address|consider|deal\s+with)\s+(?:the\s+)?(?:submission|argument)",
            r"(?:submission|argument)s?\s+(?:was|were)\s+(?:not\s+)?(?:addressed|considered|dealt\s+with)",
            r"ignored?\s+(?:the\s+)?(?:substantial\s+)?(?:submission|argument)",
        ],
        authority="Dranichnikov; Alexandria Landfill [2020] NSWCA 165",
    ),
    GroundDefinition(
        code="pf_bias_actual",
        category="procedural_fairness",
        description="Actual bias by decision-maker",
        patterns=[
            r"actual\s+bias",
            r"was\s+(?:actually\s+)?biased",
        ],
        authority="Bias rule",
    ),
    GroundDefinition(
        code="pf_bias_apprehended",
        category="procedural_fairness",
        description="Reasonable apprehension of bias",
        patterns=[
            r"apprehended\s+bias",
            r"reasonable\s+apprehension\s+of\s+bias",
            r"appearance\s+of\s+bias",
            r"might\s+(?:reasonably\s+)?(?:be\s+)?(?:thought|appear)\s+to\s+be\s+biased",
            r"ostensible\s+bias",
        ],
        authority="Bias rule; Aronson, Groves & Weeks",
    ),

    # -------------------------------------------------------------------------
    # JURISDICTIONAL ERROR
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="je_no_jurisdiction",
        category="jurisdictional_error",
        description="Lacked jurisdiction to make decision",
        patterns=[
            r"lack(?:ed|ing|s)?\s+(?:of\s+)?jurisdiction",
            r"no\s+jurisdiction",
            r"without\s+jurisdiction",
            r"did\s+not\s+have\s+jurisdiction",
            r"absence\s+of\s+jurisdiction",
        ],
        authority="Hossain [2018] HCA 34",
    ),
    GroundDefinition(
        code="je_exceeded_jurisdiction",
        category="jurisdictional_error",
        description="Exceeded statutory limits of jurisdiction",
        patterns=[
            r"exceeded?\s+(?:its\s+)?jurisdiction",
            r"beyond\s+(?:its\s+)?jurisdiction",
            r"outside\s+(?:its\s+)?jurisdiction",
            r"acted\s+ultra\s+vires",
        ],
        authority="Hossain [2018] HCA 34",
    ),
    GroundDefinition(
        code="je_constructive_failure",
        category="jurisdictional_error",
        description="Constructive failure to exercise jurisdiction (failed to decide a claim)",
        patterns=[
            r"constructive\s+failure\s+to\s+exercise\s+jurisdiction",
            r"fail(?:ed|ure)\s+to\s+(?:exercise|perform)\s+(?:its\s+)?jurisdiction",
            r"fail(?:ed|ure)\s+to\s+(?:determine|decide)\s+(?:the\s+)?(?:claim|application|matter)",
            r"did\s+not\s+(?:determine|decide)\s+(?:the\s+)?(?:claim|application)",
        ],
        authority="Dranichnikov; Alexandria Landfill",
    ),
    GroundDefinition(
        code="je_wrong_question",
        category="jurisdictional_error",
        description="Asked wrong question / misidentified the issue",
        patterns=[
            r"(?:asked|addressed)\s+(?:the\s+)?wrong\s+question",
            r"wrong\s+(?:issue|question)\s+(?:was\s+)?(?:asked|addressed|considered)",
            r"misidentified?\s+(?:the\s+)?(?:issue|question)",
            r"fail(?:ed|ure)\s+to\s+(?:identify|address)\s+(?:the\s+)?(?:correct|real|true)\s+(?:issue|question)",
        ],
        authority="Prendergast [13]",
    ),
    GroundDefinition(
        code="je_statutory_precondition",
        category="jurisdictional_error",
        description="Failed to comply with statutory precondition",
        patterns=[
            r"fail(?:ed|ure)\s+to\s+(?:comply|satisfy)\s+(?:with\s+)?(?:the\s+)?(?:statutory\s+)?(?:pre-?condition|requirement)",
            r"statutory\s+(?:pre-?condition|requirement)\s+(?:was\s+)?not\s+(?:met|satisfied|complied)",
            r"condition\s+precedent\s+(?:was\s+)?not\s+(?:met|satisfied)",
        ],
        authority="Hossain [2018] HCA 34 at [24]",
    ),

    # -------------------------------------------------------------------------
    # STATUTORY CONSTRUCTION
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="sc_misconstruction",
        category="statutory_construction",
        description="Misconstrued statute in identified way",
        patterns=[
            r"misconstru(?:ed|ction)\s+(?:of\s+)?(?:the\s+)?(?:statute|act|legislation|provision|section)",
            r"(?:statute|act|legislation|provision|section)\s+(?:was\s+)?misconstrued",
            r"erred?\s+in\s+(?:the\s+)?(?:construction|interpretation)\s+of",
            r"wrong(?:ly)?\s+(?:construed|interpreted)\s+(?:the\s+)?(?:statute|act|legislation|provision|section)",
        ],
        authority="Bianco Walling [2020] FCAFC 50 at [66]",
    ),
    GroundDefinition(
        code="sc_wrong_legal_test",
        category="statutory_construction",
        description="Applied wrong legal test/principles (evincing misconstruction)",
        patterns=[
            r"(?:applied|used)\s+(?:the\s+)?wrong\s+(?:legal\s+)?(?:test|principle|standard|criterion)",
            r"wrong\s+(?:legal\s+)?(?:test|principle|standard)\s+(?:was\s+)?(?:applied|used)",
            r"(?:applied|adopted)\s+(?:an?\s+)?(?:incorrect|erroneous)\s+(?:legal\s+)?(?:test|principle|approach)",
            r"fail(?:ed|ure)\s+to\s+apply\s+(?:the\s+)?(?:correct|proper)\s+(?:legal\s+)?(?:test|principle)",
        ],
        authority="Bimson; Roads & Maritime [40]-[45]",
    ),
    GroundDefinition(
        code="sc_technical_term",
        category="statutory_construction",
        description="Erred on meaning of technical legal term",
        patterns=[
            r"(?:meaning|definition)\s+of\s+(?:the\s+)?(?:term|expression|phrase|word)",
            r"erred?\s+(?:in\s+)?(?:as\s+to\s+)?(?:the\s+)?meaning\s+of",
            r"misconstru(?:ed|ction)\s+(?:of\s+)?(?:the\s+)?(?:term|expression|phrase|word)",
        ],
        authority="Pozzolanic prop 3",
    ),
    GroundDefinition(
        code="sc_effect_of_term",
        category="statutory_construction",
        description="Erred on effect/construction of term whose meaning is established",
        patterns=[
            r"(?:effect|operation|application)\s+of\s+(?:the\s+)?(?:provision|section|term)",
            r"erred?\s+(?:as\s+to\s+)?(?:the\s+)?(?:effect|operation)\s+of",
        ],
        authority="Pozzolanic prop 4",
    ),
    GroundDefinition(
        code="sc_contract_construction",
        category="statutory_construction",
        description="Misconstrued contract",
        patterns=[
            r"misconstru(?:ed|ction)\s+(?:of\s+)?(?:the\s+)?contract",
            r"contract\s+(?:was\s+)?misconstrued",
            r"erred?\s+in\s+(?:the\s+)?(?:construction|interpretation)\s+of\s+(?:the\s+)?contract",
            r"wrong(?:ly)?\s+(?:construed|interpreted)\s+(?:the\s+)?contract",
        ],
        authority="Bianco Walling [2020] FCAFC 50 at [66]",
    ),

    # -------------------------------------------------------------------------
    # APPLICATION OF FACTS TO LAW
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="afl_facts_necessarily_satisfy",
        category="application_of_facts_to_law",
        description="Facts as found necessarily satisfied (or did not satisfy) the statute",
        patterns=[
            r"facts\s+(?:as\s+found\s+)?(?:necessarily\s+)?(?:did\s+not\s+)?satisf(?:y|ied)\s+(?:the\s+)?(?:statute|provision|requirement)",
            r"(?:on|upon)\s+(?:the\s+)?facts\s+(?:as\s+)?found",
            r"(?:only\s+one\s+)?(?:conclusion|answer)\s+(?:was\s+)?(?:open|available)\s+(?:on\s+)?(?:the\s+)?facts",
        ],
        authority="Hope v Bathurst City Council; Azzopardi; Pozzolanic prop 5",
    ),

    # -------------------------------------------------------------------------
    # EVIDENTIARY GROUNDS
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="ev_no_evidence",
        category="evidentiary",
        description="No evidence to support finding of fact",
        patterns=[
            r"no\s+evidence\s+to\s+(?:support|justify|sustain)",
            r"(?:finding|conclusion)\s+(?:was\s+)?(?:made\s+)?(?:without|in\s+the\s+absence\s+of)\s+(?:any\s+)?evidence",
            r"no\s+(?:probative\s+)?evidence\s+(?:of|for|that)",
            r"(?:there\s+was\s+)?no\s+evidence\s+(?:before\s+)?(?:the\s+)?(?:tribunal|panel)",
        ],
        authority="Prendergast [13]",
    ),
    GroundDefinition(
        code="ev_inference_not_available",
        category="evidentiary",
        description="Drew inference not reasonably available from facts found",
        patterns=[
            r"inference\s+(?:was\s+)?not\s+(?:reasonably\s+)?(?:open|available|supported)",
            r"(?:drew|drawn)\s+(?:an?\s+)?(?:inference|conclusion)\s+(?:that\s+was\s+)?not\s+(?:open|available)",
            r"inference\s+(?:could|can)\s*(?:not|n't)\s+(?:reasonably\s+)?(?:be\s+)?(?:drawn|made)",
            r"(?:the\s+)?evidence\s+(?:did\s+)?not\s+(?:reasonably\s+)?admit\s+(?:of\s+)?(?:the\s+)?(?:inference|conclusion)",
        ],
        authority="Al-Miahi [2001] FCA 744 at [34]",
    ),
    GroundDefinition(
        code="ev_probative_evidence_ignored",
        category="evidentiary",
        description="Failed to consider probative evidence",
        patterns=[
            r"fail(?:ed|ure)\s+to\s+(?:consider|take\s+into\s+account|have\s+regard\s+to)\s+(?:the\s+)?(?:probative\s+)?evidence",
            r"(?:probative\s+)?evidence\s+(?:was\s+)?(?:ignored|overlooked|disregarded|not\s+considered)",
            r"did\s+not\s+(?:consider|take\s+into\s+account)\s+(?:the\s+)?evidence",
        ],
        authority="",
    ),
    GroundDefinition(
        code="ev_finding_not_open",
        category="evidentiary",
        description="Finding of fact not reasonably open on the evidence",
        patterns=[
            r"finding\s+(?:of\s+fact\s+)?(?:was\s+)?not\s+(?:reasonably\s+)?open",
            r"(?:finding|conclusion)\s+(?:was\s+)?not\s+(?:reasonably\s+)?(?:available|supported)\s+(?:by|on)\s+(?:the\s+)?evidence",
            r"(?:finding|conclusion)\s+(?:was\s+)?(?:against|contrary\s+to)\s+(?:the\s+)?(?:weight\s+of\s+)?(?:the\s+)?evidence",
        ],
        authority="",
    ),
    GroundDefinition(
        code="ev_fresh_evidence",
        category="evidentiary",
        description="Fresh/new evidence now available (leave ground)",
        patterns=[
            r"fresh\s+evidence",
            r"new\s+evidence\s+(?:is\s+)?(?:now\s+)?available",
            r"evidence\s+(?:that\s+)?was\s+not\s+(?:reasonably\s+)?available",
        ],
        authority="",
    ),

    # -------------------------------------------------------------------------
    # RELEVANT/IRRELEVANT CONSIDERATIONS
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="ric_mandatory_ignored",
        category="relevant_considerations",
        description="Failed to take into account mandatory consideration",
        patterns=[
            r"fail(?:ed|ure)\s+to\s+(?:take\s+into\s+account|consider|have\s+regard\s+to)\s+(?:a\s+)?(?:relevant|mandatory)\s+consideration",
            r"(?:relevant|mandatory)\s+consideration\s+(?:was\s+)?(?:not\s+)?(?:taken\s+into\s+account|considered|ignored)",
            r"fail(?:ed|ure)\s+to\s+(?:take\s+into\s+account|consider)\s+(?:a\s+)?(?:matter|factor)\s+(?:that\s+)?(?:was\s+)?(?:required|bound)\s+to",
        ],
        authority="Peko-Wallsend (1986) 162 CLR 24 at pp 39-40",
    ),
    GroundDefinition(
        code="ric_prohibited_considered",
        category="relevant_considerations",
        description="Took into account consideration prohibited by statute's purpose",
        patterns=[
            r"(?:took|taken)\s+into\s+account\s+(?:an?\s+)?(?:irrelevant|prohibited|extraneous)\s+consideration",
            r"(?:irrelevant|extraneous)\s+consideration\s+(?:was\s+)?(?:taken\s+into\s+account|considered)",
            r"(?:had|having)\s+regard\s+to\s+(?:an?\s+)?(?:irrelevant|prohibited|extraneous)\s+(?:consideration|matter|factor)",
        ],
        authority="Peko-Wallsend (1986) 162 CLR 24 at pp 39-40",
    ),

    # -------------------------------------------------------------------------
    # REASONS
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="r_failure_to_give_reasons",
        category="reasons",
        description="Failed to provide proper reasons",
        patterns=[
            r"fail(?:ed|ure)\s+to\s+(?:give|provide)\s+(?:proper|adequate|sufficient)?\s*reasons",
            r"(?:no|did\s+not\s+(?:give|provide))\s+(?:any\s+)?reasons",
            r"reasons\s+(?:were\s+)?not\s+(?:given|provided)",
        ],
        authority="Prendergast [13]",
    ),
    GroundDefinition(
        code="r_inadequate_reasons",
        category="reasons",
        description="Reasons inadequate to explain decision",
        patterns=[
            r"(?:inadequate|insufficient|deficient)\s+reasons",
            r"reasons\s+(?:were\s+)?(?:inadequate|insufficient|deficient)",
            r"reasons\s+(?:do|did)\s+not\s+(?:adequately\s+)?explain",
        ],
        authority="",
    ),
    GroundDefinition(
        code="r_failure_to_make_findings",
        category="reasons",
        description="Failed to make findings on material facts",
        patterns=[
            r"fail(?:ed|ure)\s+to\s+(?:make\s+)?(?:a\s+)?finding\s+(?:of\s+fact\s+)?(?:on|about|as\s+to)",
            r"(?:no|did\s+not\s+(?:make|reach))\s+(?:a\s+)?finding\s+(?:on|about|as\s+to)",
            r"fail(?:ed|ure)\s+to\s+(?:determine|resolve)\s+(?:a\s+)?(?:material|critical|essential)\s+(?:fact|issue|matter)",
        ],
        authority="",
    ),

    # -------------------------------------------------------------------------
    # UNREASONABLENESS
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="u_wednesbury",
        category="unreasonableness",
        description="Decision so unreasonable no reasonable decision-maker would make it",
        patterns=[
            r"wednesbury\s+unreasonabl",
            r"(?:so\s+)?unreasonable\s+(?:that\s+)?no\s+reasonable\s+(?:decision[- ]?maker|tribunal|person)",
            r"legally\s+unreasonable",
            r"manifestly\s+unreasonable",
        ],
        authority="Prendergast [13]",
    ),
    GroundDefinition(
        code="u_illogical_irrational",
        category="unreasonableness",
        description="Decision illogical or irrational",
        patterns=[
            r"(?:illogical|irrational)\s+(?:decision|conclusion|finding|reasoning)",
            r"(?:decision|conclusion|finding|reasoning)\s+(?:was\s+)?(?:illogical|irrational)",
            r"lacks?\s+(?:an?\s+)?(?:logical|rational)\s+(?:basis|foundation)",
            r"(?:internally\s+)?(?:inconsistent|contradictory)\s+(?:reasoning|findings)",
        ],
        authority="",
    ),

    # -------------------------------------------------------------------------
    # PROCEDURAL NON-COMPLIANCE
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="pnc_statutory_procedure",
        category="procedural_non_compliance",
        description="Required statutory procedure not observed",
        patterns=[
            r"(?:statutory\s+)?procedure\s+(?:was\s+)?not\s+(?:observed|followed|complied)",
            r"fail(?:ed|ure)\s+to\s+(?:observe|follow|comply\s+with)\s+(?:the\s+)?(?:statutory\s+)?procedure",
            r"(?:procedural\s+)?(?:requirements?\s+)?(?:of\s+)?(?:the\s+)?(?:act|statute|legislation)\s+(?:was|were)\s+not\s+(?:observed|followed|met)",
        ],
        authority="",
    ),
    GroundDefinition(
        code="pnc_tribunal_rules",
        category="procedural_non_compliance",
        description="Tribunal rules not followed",
        patterns=[
            r"(?:tribunal\s+)?rules?\s+(?:was|were)\s+not\s+(?:followed|observed|complied)",
            r"fail(?:ed|ure)\s+to\s+(?:follow|observe|comply\s+with)\s+(?:the\s+)?(?:tribunal\s+)?rules?",
            r"breach\s+of\s+(?:the\s+)?(?:tribunal\s+)?rules?",
        ],
        authority="",
    ),

    # -------------------------------------------------------------------------
    # OTHER (catch-all for grounds that don't fit above categories)
    # -------------------------------------------------------------------------
    GroundDefinition(
        code="other_error_of_law",
        category="other",
        description="Other error of law not otherwise categorised",
        patterns=[
            r"error\s+of\s+law",
            r"question\s+of\s+law",
        ],
        authority="",
    ),
]


# Mapping from code to GroundDefinition for quick lookup
GROUND_BY_CODE: dict[str, GroundDefinition] = {g.code: g for g in GROUNDS}

# Mapping from category to list of grounds
GROUNDS_BY_CATEGORY: dict[str, list[GroundDefinition]] = {}
for g in GROUNDS:
    if g.category not in GROUNDS_BY_CATEGORY:
        GROUNDS_BY_CATEGORY[g.category] = []
    GROUNDS_BY_CATEGORY[g.category].append(g)


# =============================================================================
# INTERLOCUTORY DETECTION
# =============================================================================

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


# =============================================================================
# OUTCOME DETECTION
# =============================================================================

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


# =============================================================================
# CLASSIFICATION FUNCTIONS
# =============================================================================

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
    """Determine if decision is interlocutory based on content."""
    # Check catchwords first - strong signal
    for pattern in INTERLOCUTORY_PATTERNS:
        if re.search(pattern, catchwords, re.IGNORECASE):
            logger.debug(f"Interlocutory: matched '{pattern}' in catchwords")
            return True

    # If text contains clear final appeal language, not interlocutory
    has_allowed = any(re.search(p, text, re.IGNORECASE) for p in APPEAL_ALLOWED_PATTERNS)
    has_dismissed = any(re.search(p, text, re.IGNORECASE) for p in APPEAL_DISMISSED_PATTERNS)

    if has_allowed or has_dismissed:
        return False

    # Check body for interlocutory patterns if no clear final outcome
    for pattern in INTERLOCUTORY_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return True

    return False


def _extract_grounds(text: str) -> list[str]:
    """Extract grounds of appeal from decision text.

    Returns list of ground codes (e.g., 'pf_no_hearing', 'ev_no_evidence').
    Attempts to match specific grounds first before falling back to broader categories.
    Multiple grounds may be matched.
    """
    found_grounds: list[str] = []
    matched_categories: set[str] = set()

    # First pass: try to match specific grounds (excluding 'other' category)
    for ground in GROUNDS:
        if ground.category == "other":
            continue
        for pattern in ground.patterns:
            if re.search(pattern, text, re.IGNORECASE):
                if ground.code not in found_grounds:
                    found_grounds.append(ground.code)
                    matched_categories.add(ground.category)
                    logger.debug(f"Matched ground: {ground.code} via pattern '{pattern}'")
                break

    # Second pass: check for 'other' category only if no specific grounds matched
    # and there's a generic error of law reference
    if not found_grounds:
        for ground in GROUNDS:
            if ground.category == "other":
                for pattern in ground.patterns:
                    if re.search(pattern, text, re.IGNORECASE):
                        if ground.code not in found_grounds:
                            found_grounds.append(ground.code)
                            logger.debug(f"Matched fallback ground: {ground.code}")
                        break

    return found_grounds


def _determine_outcome(text: str) -> Literal["allowed", "dismissed"] | None:
    """Determine appeal outcome from decision text."""
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

    Returns list of ground codes that were upheld.
    Falls back to returning all grounds if specific ones can't be identified.
    """
    successful: list[str] = []

    # Patterns indicating a ground was upheld
    success_indicators = [
        r"(?:ground|complaint|submission).*(?:is\s+)?(?:made\s+out|established|upheld|succeeds|accepted)",
        r"(?:we|the\s+panel)\s+(?:find|accept|conclude|agree)",
        r"(?:the\s+)?(?:tribunal|member)\s+erred",
        r"(?:there\s+was\s+)?(?:a\s+|an\s+)?(?:error|failure|breach|denial)",
    ]

    for ground_code in all_grounds:
        ground_def = GROUND_BY_CODE.get(ground_code)
        if not ground_def:
            continue

        # Check if any of the ground's patterns appear near success indicators
        for ground_pattern in ground_def.patterns:
            for success_pattern in success_indicators:
                # Look for ground pattern within 200 chars of success indicator
                combined_pattern = f"(?:{success_pattern}).{{0,200}}(?:{ground_pattern})|(?:{ground_pattern}).{{0,200}}(?:{success_pattern})"
                if re.search(combined_pattern, text, re.IGNORECASE | re.DOTALL):
                    if ground_code not in successful:
                        successful.append(ground_code)
                        logger.debug(f"Identified successful ground: {ground_code}")
                    break
            if ground_code in successful:
                break

    # Fallback: if appeal allowed but couldn't identify specific grounds, return all
    if not successful and all_grounds:
        logger.debug("Could not identify specific successful grounds, returning all")
        return all_grounds

    return successful


def get_ground_info(code: str) -> dict | None:
    """Get information about a ground by its code.

    Returns dict with code, category, description, authority.
    Returns None if code not found.
    """
    ground = GROUND_BY_CODE.get(code)
    if not ground:
        return None
    return {
        "code": ground.code,
        "category": ground.category,
        "description": ground.description,
        "authority": ground.authority,
    }


def get_all_categories() -> list[str]:
    """Return list of all ground categories."""
    return list(GROUNDS_BY_CATEGORY.keys())


def get_grounds_for_category(category: str) -> list[str]:
    """Return list of ground codes for a given category."""
    grounds = GROUNDS_BY_CATEGORY.get(category, [])
    return [g.code for g in grounds]
