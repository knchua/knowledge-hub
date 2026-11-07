"""Currency rendering tests: no Streamlit or provider calls."""
from services.summary_render_service import escape_markdown_currency


def test_escapes_both_dollar_symbols_without_editing_amounts():
    raw = "S$218,000 has been spent, with forecast S$472,000."
    assert escape_markdown_currency(raw) == (
        r"S\$218,000 has been spent, with forecast S\$472,000."
    )
    assert raw == "S$218,000 has been spent, with forecast S$472,000."


def test_escapes_math_delimiters_even_without_s_prefix():
    assert escape_markdown_currency("$100 then $200") == r"\$100 then \$200"


def test_does_not_double_escape_existing_escaped_dollar():
    assert escape_markdown_currency(r"S\$218,000") == r"S\$218,000"


def test_non_currency_markdown_is_unchanged():
    raw = "**Key findings** [P24] and risks R-01 / R-02"
    assert escape_markdown_currency(raw) == raw
