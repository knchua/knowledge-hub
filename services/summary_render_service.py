"""Presentation-only escaping for untrusted, source-grounded summaries.

No document processing, storage, logging or OpenAI calls.
"""


def escape_markdown_currency(value: str) -> str:
    """Prevent single-dollar math parsing in Streamlit Markdown.

    Escape all unescaped dollar signs, not only ``S$`` before a digit.
    The model may insert whitespace or other punctuation around an amount.
    This is a display transformation; the stored text remains unchanged.
    """
    if not isinstance(value, str):
        raise TypeError("Summary must be text")
    out = []
    backslashes = 0
    for char in value:
        if char == "$" and backslashes % 2 == 0:
            out.append("\\")
        out.append(char)
        backslashes = backslashes + 1 if char == "\\" else 0
    return "".join(out)
