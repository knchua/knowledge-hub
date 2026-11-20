import pytest

from services.summarisation_service import (
    _extract_labels,
    InvalidSourceReferences,
)


@pytest.mark.parametrize(
    "text, allowed, expected",
    [
        ("No citations", {"P1"}, "citation_missing"),
        ("Unsupported [P99]", {"P1"}, "citation_unknown"),
        ("Valid [P1] and malformed [P 2]", {"P1", "P2"}, "citation_malformed"),
    ],
)
def test_citation_failure_categories(text, allowed, expected):
    with pytest.raises(InvalidSourceReferences, match="source references") as exc:
        _extract_labels(text, allowed)

    assert exc.value.category == expected


def test_valid_ocr_citations_unchanged():
    assert _extract_labels(
        "First step [P1]. Second step [P2].",
        {"P1", "P2"},
    ) == (0, 1)
