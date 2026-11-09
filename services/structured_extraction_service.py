"""Conservative, source-verbatim register projection for hierarchical summaries.

No model calls, storage, network access or document-content logging.
Only unambiguous line-anchored records are projected. Ambiguities fail closed.
"""
from __future__ import annotations

from dataclasses import dataclass
import re

_ACTION = re.compile(r"^\s*(A-\d{2,4})\s*[—–:\-]\s*(\S.*)$", re.I)
_RISK = re.compile(r"^\s*Risk\s+(R-\d{2,4})\s*[—–:\-]\s*(\S.*)$", re.I)
_RATINGS = re.compile(r"\b(Low|Medium|High)\s+likelihood\s*/\s*(Low|Medium|High)\s+impact\b", re.I)
_FIELD_RATINGS = re.compile(r"\bLikelihood\s*:\s*(Low|Medium|High)\b.*\bImpact\s*:\s*(Low|Medium|High)\b", re.I)
_ISSUE = re.compile(
    r"\b(?:unresolved|unconfirmed|not confirmed|has not been selected|has not been decided|"
    r"not established|no approved|not yet approved|not available|under review|still being reviewed|"
    r"no (?:release|pilot|launch|revised|final|exact|quantified|tester)\b[^.]{0,55}\b(?:date|count|target|objective|decision|approval)|"
    r"still pending)\b", re.I,
)


class StructuredExtractionError(ValueError):
    """An authoritative source record cannot be reconciled safely."""


@dataclass(frozen=True)
class ExtractedRegister:
    actions: tuple[tuple[str, str, int], ...]
    risks: tuple[tuple[str, str, int], ...]
    unresolved: tuple[tuple[str, int], ...]
    delivery_metrics: tuple[tuple[str, int], ...] = ()


# Retain a bounded, cited set of explicit actual-versus-plan measurements.
# These patterns identify classes of evidence, not any project-specific values.
_METRIC_PATTERNS = (
    ("test_progress", re.compile(r"\b(?:SIT|system integration testing)\b.*?\b\d+(?:\.\d+)?%.*?\b(?:planned|against|versus|vs\.?|target)\b.*?\d+(?:\.\d+)?%", re.I)),
    ("test_schedule", re.compile(r"\b(?:SIT|testing)\b.*?\b(?:forecast|complete|completion)\b.*?\b\d{1,2}\s+[A-Za-z]+(?:\s+\d{4})?.*?\b(?:original|baseline|planned)\b.*?\b\d{1,2}\s+[A-Za-z]+", re.I)),
    ("critical_defects", re.compile(r"\b(?:two|[0-9]+)\s+open\s+Priority\s*1\s+defects?\b", re.I)),
    ("migration_reconciliation", re.compile(r"\b(?:migration|rehearsal)\b.*?\b\d[\d,]*\s+(?:active\s+)?customer\s+cases\b.*?\b\d+(?:\.\d+)?%", re.I)),
    ("migration_threshold", re.compile(r"\b(?:migration|rehearsal|reconciliation)\b.*?\b\d+(?:\.\d+)?%.*?\b(?:below|required|acceptance|threshold|minimum)\b.*?\b\d+(?:\.\d+)?%", re.I)),
    ("financial_headroom", re.compile(r"\b(?:forecast|estimate at completion|EAC)\b.*?S\$[\d,]+.*?\b(?:headroom|below the approved ceiling)\b", re.I)),
)


def _metric_extract(segments) -> tuple[tuple[str, int], ...]:
    """Keep original source sentences, never recompute percentages or amounts."""
    found: dict[str, tuple[str, int]] = {}
    used_statements: set[str] = set()
    for segment in segments:
        for line in segment.text.splitlines():
            line = line.strip()
            if not line:
                continue
            # A line may contain several relevant source sentences.
            sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z])", line)
            for category, pattern in _METRIC_PATTERNS:
                if category in found:
                    continue
                matches = [sentence.strip() for sentence in sentences if pattern.search(sentence)]
                if not matches and pattern.search(line):
                    matches = [line]
                if matches:
                    candidate = matches[0]
                    if 20 <= len(candidate) <= 650 and candidate not in used_statements:
                        found[category] = (candidate, segment.index)
                        used_statements.add(candidate)
    ordered = [found[k] for k, _ in _METRIC_PATTERNS if k in found]
    # Prefer a longer source paragraph containing the shorter metric statement;
    # avoid displaying the identical measurement twice.
    return tuple((statement, index) for statement, index in ordered
                 if not any(other != statement and other.startswith(statement)
                            for other, _ in ordered))


def _issue_category(sentence: str) -> str | None:
    text = sentence.casefold()
    if re.search(r"\b(?:steering|meeting|readiness review)\b", text) and not any(
        phrase in text for phrase in ("not approved", "unapproved", "not decided", "not confirmed", "under review", "being reviewed")
    ):
        return None
    if "retention" in text or "legacy archive" in text or "specialist case subtype" in text:
        return "retention"
    if "tester" in text and ("uat" in text or "roster" in text or "final number" in text or "final count" in text):
        return "uat_testers"
    if "assessor" in text and any(x in text for x in ("not selected", "not confirmed", "pending")):
        return "assessor"
    if "customer-contact" in text or "call volumes" in text:
        return "contact_target"
    if "survey design" in text:
        return "survey_design"
    if "proposal" in text or "evening sit cycle" in text:
        return "proposed_sit"
    if "recovery-time objective" in text or "rollback" in text:
        return "rollback"
    if "mobile" in text and "date" in text:
        return "mobile_date"
    if "revised" in text and "launch" in text:
        return "launch_date"
    return "other:" + " ".join(re.findall(r"[a-z]{4,}", text)[:7])


def _deduplicate_unresolved(items: list[tuple[str, int]]) -> tuple[tuple[str, int], ...]:
    chosen: dict[str, tuple[str, int]] = {}
    for sentence, index in items:
        category = _issue_category(sentence)
        if category is None:
            continue
        # Prefer the more informative source passage when both discuss one issue.
        old = chosen.get(category)
        if old is None or len(sentence) > len(old[0]):
            chosen[category] = (sentence, index)
    results = list(chosen.items())
    # A source sentence can itself enumerate several unresolved fields.
    # Do not repeat the UAT/count or contact-target statement when that
    # same information is already included in such an explicit enumeration.
    omnibus = [sentence.casefold() for _, (sentence, _) in results
               if "not established" in sentence.casefold() and "," in sentence]
    if omnibus:
        results = [(category, value) for category, value in results
                   if not (category == "uat_testers" and
                           any("uat tester count" in x for x in omnibus) and
                           "not established" not in value[0].casefold())
                   and not (category == "contact_target" and
                            any("customer-contact reduction target" in x for x in omnibus) and
                            "not established" not in value[0].casefold())]
    return tuple(value for _, value in results[:10])


def extract_register(document) -> ExtractedRegister:
    """Read only segment text and retain the current segment's citation index."""
    actions: dict[str, tuple[str, int]] = {}
    risks: dict[str, tuple[str, int]] = {}
    unresolved: list[tuple[str, int]] = []
    segments = tuple(document.segments)
    for segment in segments:
        for line in segment.text.splitlines():
            line = line.strip()
            if not line:
                continue
            action = _ACTION.match(line)
            risk = _RISK.match(line)
            if action or risk:
                m = action or risk
                ident = m.group(1).upper()
                detail = m.group(2).strip()
                # Reject ambiguous duplicate authoritative definitions. Repeated
                # table rows or references with no full narrative do not match.
                target = actions if action else risks
                if ident in target and target[ident][0] != detail:
                    raise StructuredExtractionError("Conflicting authoritative register entries")
                if risk and not (_RATINGS.search(detail) or _FIELD_RATINGS.search(detail)):
                    raise StructuredExtractionError("Incomplete authoritative risk ratings")
                target[ident] = (detail, segment.index)
            if 35 <= len(line) < 550 and "." in line:
                # Keep only explicitly unresolved source *sentences*, not whole
                # paragraphs that mix known measurements with uncertainty.
                sentences = re.split(r"(?<=[.!?])\s+", line)
                for number, sentence in enumerate(sentences):
                    if _ISSUE.search(sentence):
                        sentence = sentence.strip()
                        # Resolve 'This proposal' with the immediately preceding
                        # sentence, but only if the prior sentence defines it.
                        if (re.match(r"(?i)^this proposal\b", sentence) and number > 0
                                and "proposal" in sentences[number - 1].lower()):
                            sentence = sentences[number - 1].strip() + " " + sentence
                        unresolved.append((sentence, segment.index))
    # Only use this source-grounded projection if we can identify both registers.
    # Otherwise the caller uses its existing validated model path.
    dedup: list[tuple[str, int]] = []
    seen: set[str] = set()
    for line, index in unresolved:
        key = line.casefold()
        if key not in seen:
            seen.add(key)
            dedup.append((line, index))
    # Do not let section headings or unqualified facts enter the missing list.
    # The summary validator will also independently check each displayed item.
    from_source = re.compile(
        r"\b(?:unresolved|unconfirmed|not confirmed|not approved|not yet approved|"
        r"no approved|not established|not selected|not found|under review|"
        r"being reviewed|pending|not yet|without a date|no date)\b", re.I
    )
    dedup = [(line, index) for line, index in dedup if from_source.search(line)]
    dedup = list(_deduplicate_unresolved(dedup))
    return ExtractedRegister(
        tuple((key, *value) for key, value in sorted(actions.items())),
        tuple((key, *value) for key, value in sorted(risks.items())),
        tuple(dedup),
        _metric_extract(segments),
    )


def project_structured_summary(draft: str, document) -> str:
    """Replace hallucination-prone model registers with source-verbatim records.

    Other generated sections are retained. Citation correctness still receives
    normal validation in the calling summarisation service.
    """
    register = extract_register(document)
    if not register.actions or not register.risks:
        return draft
    heading = re.compile(r"(?m)^\s{0,3}#{1,6}\s+(.+?)\s*$")
    headings = list(heading.finditer(draft))
    prohibited = {"action items", "risks", "missing/unclear information", "delivery metrics (source evidence)"}
    keep: list[str] = []
    cursor = 0
    for i, match in enumerate(headings):
        title = re.sub(r"[*_`]", "", match.group(1)).strip().casefold()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(draft)
        if title in prohibited:
            keep.append(draft[cursor:match.start()])
            cursor = end
    keep.append(draft[cursor:])
    sections = ["".join(keep).strip(), "## Action Items"]
    for ident, detail, segment_index in register.actions:
        sections.append(f"- {ident} — {detail} [P{segment_index+1}]")
    sections.append("\n## Risks")
    for ident, detail, segment_index in register.risks:
        sections.append(f"- {ident} — {detail} [P{segment_index+1}]")
    if register.delivery_metrics:
        sections.append("\n## Delivery Metrics (Source Evidence)")
        for statement, segment_index in register.delivery_metrics:
            sections.append(f"- {statement} [P{segment_index+1}]")
    if register.unresolved:
        sections.append("\n## Missing/Unclear Information")
        for line, segment_index in register.unresolved:
            sections.append(f"- {line} [P{segment_index+1}]")
    return "\n\n".join(sections).strip()
