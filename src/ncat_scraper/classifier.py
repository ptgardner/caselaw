"""Classifier for NCAT Appeal Panel decisions.

Classifies decisions based on:
1. Decision type: final (appeal allowed/dismissed) vs interlocutory (costs, stays, etc)
2. Grounds of appeal - granular taxonomy based on Prendergast and subsequent authorities
3. Outcome (for final decisions)
4. Successful grounds (for allowed appeals)

Optimizations:
- Pre-compiled regex patterns for performance
- Negative patterns to avoid false positives
- Context-aware matching (section extraction)
- Confidence scoring for matches

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
from dataclasses import dataclass, field
from typing import Literal

from .models import Decision, ScrapedDecisionData

logger = logging.getLogger(__name__)


# =============================================================================
# GROUND TAXONOMY WITH COMPILED PATTERNS
# =============================================================================

@dataclass
class GroundDefinition:
    """Definition of a ground of appeal with pre-compiled detection patterns."""
    code: str
    category: str
    description: str
    patterns: list[str]
    authority: str = ""
    weight: float = 1.0  # Higher weight = more reliable pattern
    _compiled: list[re.Pattern] = field(default_factory=list, repr=False, compare=False)

    def __post_init__(self):
        """Pre-compile regex patterns for performance."""
        self._compiled = [re.compile(p, re.IGNORECASE) for p in self.patterns]

    def match(self, text: str) -> tuple[bool, float, str]:
        """Check if any pattern matches the text.

        Returns:
            Tuple of (matched: bool, confidence: float, matched_text: str)
        """
        for compiled in self._compiled:
            match = compiled.search(text)
            if match:
                return True, self.weight, match.group(0)
        return False, 0.0, ""


@dataclass
class ClassifiedGround:
    """A ground that was matched with confidence information."""
    code: str
    category: str
    description: str
    authority: str
    confidence: float
    matched_text: str
    in_relevant_section: bool = False

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "category": self.category,
            "description": self.description,
            "authority": self.authority,
            "confidence": self.confidence,
            "matched_text": self.matched_text,
            "in_relevant_section": self.in_relevant_section,
        }


# Negation patterns - if these appear before a ground pattern, it's likely a false positive
NEGATION_PATTERNS = [
    re.compile(r"no\s+(?:denial\s+of\s+|breach\s+of\s+|failure\s+to\s+)?", re.IGNORECASE),
    re.compile(r"not\s+(?:a\s+)?(?:denial|breach|failure)", re.IGNORECASE),
    re.compile(r"did\s+not\s+(?:constitute|amount\s+to)", re.IGNORECASE),
    re.compile(r"there\s+was\s+no\s+", re.IGNORECASE),
    re.compile(r"cannot\s+(?:be\s+said|succeed)", re.IGNORECASE),
    re.compile(r"does\s+not\s+(?:establish|demonstrate|show)", re.IGNORECASE),
    re.compile(r"fails?\s+to\s+(?:establish|demonstrate|show)", re.IGNORECASE),
    re.compile(r"(?:is|was)\s+not\s+(?:established|made\s+out|demonstrated)", re.IGNORECASE),
]


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
        weight=0.9,
    ),
    GroundDefinition(
        code="pf_no_notice",
        category="procedural_fairness",
        description="No notice of case to answer or issues to be decided",
        patterns=[
            r"no\s+notice\s+of\s+(?:the\s+)?(?:case|issues?|matters?)",
            r"not\s+(?:given|provided)\s+(?:adequate\s+)?notice",
            r"without\s+(?:adequate\s+)?notice",
            r"unaware\s+of\s+(?:the\s+)?(?:case|issues?)",
        ],
        authority="Fair hearing rule",
        weight=0.85,
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
        weight=0.85,
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
        weight=0.9,
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
        weight=0.8,
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
        weight=0.95,
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
        weight=0.9,
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
        weight=0.9,
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
        weight=0.9,
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
        weight=0.85,
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
        weight=0.85,
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
        weight=0.85,
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
        weight=0.9,
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
        weight=0.9,
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
        weight=0.8,
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
        weight=0.8,
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
        weight=0.9,
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
        weight=0.85,
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
        weight=0.85,
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
        weight=0.85,
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
        weight=0.8,
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
        weight=0.8,
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
        weight=0.9,
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
        weight=0.85,
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
        weight=0.85,
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
        weight=0.85,
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
        weight=0.8,
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
        weight=0.8,
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
        weight=0.9,
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
        weight=0.85,
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
        weight=0.85,
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
        weight=0.8,
    ),

    # -------------------------------------------------------------------------
    # OTHER (catch-all)
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
        weight=0.5,  # Low weight - fallback only
    ),
]


# Build lookup dictionaries
GROUND_BY_CODE: dict[str, GroundDefinition] = {g.code: g for g in GROUNDS}

GROUNDS_BY_CATEGORY: dict[str, list[GroundDefinition]] = {}
for g in GROUNDS:
    if g.category not in GROUNDS_BY_CATEGORY:
        GROUNDS_BY_CATEGORY[g.category] = []
    GROUNDS_BY_CATEGORY[g.category].append(g)


# =============================================================================
# SECTION EXTRACTION FOR CONTEXT-AWARE MATCHING
# =============================================================================

SECTION_PATTERNS = {
    "grounds": re.compile(
        r"(?:grounds?\s+of\s+appeal|(?:the\s+)?appellant\s+(?:contends?|submits?|argues?)).*?(?=\n\n|\Z|(?:consideration|discussion|analysis|decision))",
        re.IGNORECASE | re.DOTALL
    ),
    "orders": re.compile(
        r"(?:orders?|decision)\s*[:\n](.*?)(?:\n\n|\Z)",
        re.IGNORECASE | re.DOTALL
    ),
    "discussion": re.compile(
        r"(?:discussion|analysis|consideration).*?(?=\n\n(?:orders?|decision|conclusion)|\Z)",
        re.IGNORECASE | re.DOTALL
    ),
}


def _extract_section(text: str, section: str) -> str:
    """Extract a specific section from the decision text."""
    pattern = SECTION_PATTERNS.get(section)
    if not pattern:
        return ""
    match = pattern.search(text)
    return match.group(0) if match else ""


# =============================================================================
# INTERLOCUTORY DETECTION (pre-compiled)
# =============================================================================

INTERLOCUTORY_PATTERNS = [
    re.compile(r"\bcosts?\b.*\b(application|order|assessment)\b", re.IGNORECASE),
    re.compile(r"\bstay\b.*\b(application|order|granted|refused)\b", re.IGNORECASE),
    re.compile(r"\bextension\s+of\s+time\b", re.IGNORECASE),
    re.compile(r"\bleave\s+to\s+appeal\b", re.IGNORECASE),
    re.compile(r"\badjournment\b", re.IGNORECASE),
    re.compile(r"\binterlocutory\b", re.IGNORECASE),
    re.compile(r"\bprocedural\b.*\border\b", re.IGNORECASE),
    re.compile(r"\bamendment\b.*\b(application|order)\b", re.IGNORECASE),
    re.compile(r"\bjoinder\b", re.IGNORECASE),
    re.compile(r"\bdismissed\s+as\s+incompetent\b", re.IGNORECASE),
    re.compile(r"\bstruck\s+out\b", re.IGNORECASE),
]


# =============================================================================
# OUTCOME DETECTION (pre-compiled)
# =============================================================================

APPEAL_ALLOWED_PATTERNS = [
    re.compile(r"appeal\s+(?:is\s+)?allowed", re.IGNORECASE),
    re.compile(r"the\s+appeal\s+(?:is\s+)?allowed", re.IGNORECASE),
    re.compile(r"appeals?\s+(?:are\s+)?allowed", re.IGNORECASE),
    re.compile(r"allow\s+the\s+appeal", re.IGNORECASE),
]

APPEAL_DISMISSED_PATTERNS = [
    re.compile(r"appeal\s+(?:is\s+)?dismissed", re.IGNORECASE),
    re.compile(r"the\s+appeal\s+(?:is\s+)?dismissed", re.IGNORECASE),
    re.compile(r"appeals?\s+(?:are\s+)?dismissed", re.IGNORECASE),
    re.compile(r"dismiss\s+the\s+appeal", re.IGNORECASE),
]


# =============================================================================
# CLASSIFICATION FUNCTIONS
# =============================================================================

def _is_negated(text: str, match_start: int) -> bool:
    """Check if a match is preceded by a negation pattern."""
    # Look at the 50 characters before the match
    context_start = max(0, match_start - 50)
    context = text[context_start:match_start]

    for pattern in NEGATION_PATTERNS:
        if pattern.search(context):
            return True
    return False


def classify_decision(scraped_data: ScrapedDecisionData) -> Decision:
    """Classify a scraped decision with confidence scoring."""
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

    # Final decision - extract grounds with confidence
    classified_grounds = _extract_grounds_with_confidence(combined_text)
    ground_codes = [g.code for g in classified_grounds]

    outcome = _determine_outcome(text)
    successful_grounds = []

    if outcome == "allowed":
        successful_grounds = _extract_successful_grounds(text, ground_codes)

    return Decision(
        url=scraped_data.url,
        medium_neutral_citation=scraped_data.medium_neutral_citation,
        year=scraped_data.year,
        decision_makers=scraped_data.decision_makers,
        decision_type="final",
        grounds_of_appeal=ground_codes,
        outcome=outcome,
        successful_grounds=successful_grounds,
    )


def classify_decision_detailed(scraped_data: ScrapedDecisionData) -> tuple[Decision, list[ClassifiedGround]]:
    """Classify a decision and return detailed ground information with confidence."""
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
        ), []

    classified_grounds = _extract_grounds_with_confidence(combined_text)
    ground_codes = [g.code for g in classified_grounds]

    outcome = _determine_outcome(text)
    successful_grounds = []

    if outcome == "allowed":
        successful_grounds = _extract_successful_grounds(text, ground_codes)

    decision = Decision(
        url=scraped_data.url,
        medium_neutral_citation=scraped_data.medium_neutral_citation,
        year=scraped_data.year,
        decision_makers=scraped_data.decision_makers,
        decision_type="final",
        grounds_of_appeal=ground_codes,
        outcome=outcome,
        successful_grounds=successful_grounds,
    )

    return decision, classified_grounds


def _is_interlocutory(text: str, catchwords: str) -> bool:
    """Determine if decision is interlocutory."""
    # Check catchwords first
    for pattern in INTERLOCUTORY_PATTERNS:
        if pattern.search(catchwords):
            logger.debug(f"Interlocutory: matched in catchwords")
            return True

    # If clear final outcome, not interlocutory
    has_allowed = any(p.search(text) for p in APPEAL_ALLOWED_PATTERNS)
    has_dismissed = any(p.search(text) for p in APPEAL_DISMISSED_PATTERNS)

    if has_allowed or has_dismissed:
        return False

    # Check body for interlocutory patterns
    for pattern in INTERLOCUTORY_PATTERNS:
        if pattern.search(text):
            return True

    return False


def _extract_grounds_with_confidence(text: str) -> list[ClassifiedGround]:
    """Extract grounds with confidence scores and negation checking."""
    found_grounds: list[ClassifiedGround] = []

    # Extract relevant sections for context-aware matching
    grounds_section = _extract_section(text, "grounds")

    # First pass: specific grounds (excluding 'other')
    for ground in GROUNDS:
        if ground.category == "other":
            continue

        matched, base_confidence, matched_text = ground.match(text)
        if not matched:
            continue

        # Find match position for negation check
        match_pos = text.find(matched_text.lower())

        # Check for negation
        if match_pos >= 0 and _is_negated(text, match_pos):
            logger.debug(f"Skipping negated match: {ground.code} - '{matched_text}'")
            continue

        # Boost confidence if in grounds section
        in_section = grounds_section and matched_text.lower() in grounds_section.lower()
        confidence = base_confidence * (1.2 if in_section else 1.0)
        confidence = min(confidence, 1.0)  # Cap at 1.0

        found_grounds.append(ClassifiedGround(
            code=ground.code,
            category=ground.category,
            description=ground.description,
            authority=ground.authority,
            confidence=round(confidence, 2),
            matched_text=matched_text,
            in_relevant_section=in_section,
        ))
        logger.debug(f"Matched: {ground.code} (conf={confidence:.2f}) - '{matched_text}'")

    # Second pass: 'other' category only if no specific grounds
    if not found_grounds:
        for ground in GROUNDS:
            if ground.category != "other":
                continue
            matched, base_confidence, matched_text = ground.match(text)
            if matched:
                found_grounds.append(ClassifiedGround(
                    code=ground.code,
                    category=ground.category,
                    description=ground.description,
                    authority=ground.authority,
                    confidence=round(base_confidence, 2),
                    matched_text=matched_text,
                    in_relevant_section=False,
                ))
                logger.debug(f"Matched fallback: {ground.code}")

    return found_grounds


def _extract_grounds(text: str) -> list[str]:
    """Extract ground codes from decision text (simplified interface)."""
    classified = _extract_grounds_with_confidence(text)
    return [g.code for g in classified]


def _determine_outcome(text: str) -> Literal["allowed", "dismissed"] | None:
    """Determine appeal outcome from decision text."""
    # Look in orders section first
    orders_section = _extract_section(text, "orders")
    search_text = orders_section if orders_section else text[-2000:]

    for pattern in APPEAL_ALLOWED_PATTERNS:
        if pattern.search(search_text):
            return "allowed"

    for pattern in APPEAL_DISMISSED_PATTERNS:
        if pattern.search(search_text):
            return "dismissed"

    # Fallback: full text
    for pattern in APPEAL_ALLOWED_PATTERNS:
        if pattern.search(text):
            return "allowed"

    for pattern in APPEAL_DISMISSED_PATTERNS:
        if pattern.search(text):
            return "dismissed"

    logger.warning("Could not determine appeal outcome")
    return None


def _extract_successful_grounds(text: str, all_grounds: list[str]) -> list[str]:
    """Extract which grounds were successful."""
    successful: list[str] = []

    success_patterns = [
        re.compile(r"(?:ground|complaint|submission).*(?:is\s+)?(?:made\s+out|established|upheld|succeeds|accepted)", re.IGNORECASE),
        re.compile(r"(?:we|the\s+panel)\s+(?:find|accept|conclude|agree)", re.IGNORECASE),
        re.compile(r"(?:the\s+)?(?:tribunal|member)\s+erred", re.IGNORECASE),
        re.compile(r"(?:there\s+was\s+)?(?:a\s+|an\s+)?(?:error|failure|breach|denial)", re.IGNORECASE),
    ]

    for ground_code in all_grounds:
        ground_def = GROUND_BY_CODE.get(ground_code)
        if not ground_def:
            continue

        for compiled in ground_def._compiled:
            match = compiled.search(text)
            if not match:
                continue

            match_pos = match.start()
            # Check if success indicator within 200 chars
            context = text[max(0, match_pos - 200):min(len(text), match_pos + 200)]

            for success_pattern in success_patterns:
                if success_pattern.search(context):
                    if ground_code not in successful:
                        successful.append(ground_code)
                        logger.debug(f"Successful ground: {ground_code}")
                    break
            if ground_code in successful:
                break

    # Fallback
    if not successful and all_grounds:
        logger.debug("Could not identify specific successful grounds, returning all")
        return all_grounds

    return successful


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def get_ground_info(code: str) -> dict | None:
    """Get information about a ground by its code."""
    ground = GROUND_BY_CODE.get(code)
    if not ground:
        return None
    return {
        "code": ground.code,
        "category": ground.category,
        "description": ground.description,
        "authority": ground.authority,
        "weight": ground.weight,
    }


def get_all_categories() -> list[str]:
    """Return list of all ground categories."""
    return list(GROUNDS_BY_CATEGORY.keys())


def get_grounds_for_category(category: str) -> list[str]:
    """Return list of ground codes for a given category."""
    grounds = GROUNDS_BY_CATEGORY.get(category, [])
    return [g.code for g in grounds]
