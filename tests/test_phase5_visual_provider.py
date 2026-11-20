"""M2.3 fake-provider tests: zero external calls, zero application state writes."""
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PIL import Image

from services.visual_provider_service import (
    VisionBudget, VisualProviderError, analyze_visual_image,
)


def image_bytes(width=1500, height=900, fmt="PNG"):
    im = Image.new("RGB", (width, height), "white")
    buffer = io.BytesIO()
    im.save(buffer, format=fmt)
    return buffer.getvalue()


def budget(**kwargs):
    return VisionBudget(max_estimated_usd=.10, input_price_per_million_usd=.40,
                        output_price_per_million_usd=1.60, **kwargs)


def fake_client(result=None, status="completed", usage=True):
    if result is None:
        result = {"recognized_text": "Submit request", "visual_description": "Box A points to box B",
                  "unreadable_regions": [], "warnings": [], "source_id": "docx_image_1"}
    value = SimpleNamespace(status=status, output_text=json.dumps(result),
                            usage=SimpleNamespace(input_tokens=2356, output_tokens=195) if usage else None)
    client = SimpleNamespace(responses=SimpleNamespace(create=Mock(return_value=value)))
    return client


def test_fake_response_and_contract():
    c = fake_client()
    b = budget()
    result = analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=b, client=c)
    assert result.recognized_text == "Submit request"
    assert result.source_id == "docx_image_1"
    assert result.estimated_cost_usd == pytest.approx(.0012544)
    assert b.calls_attempted == 1 and b.estimated_spent_usd == pytest.approx(.0012544)
    sent = c.responses.create.call_args.kwargs
    assert sent["store"] is False and sent["model"] == "gpt-4.1-mini"
    assert sent["max_output_tokens"] == 1200
    assert sent["text"]["format"]["strict"] is True
    message = sent["input"][0]["content"][1]
    assert message["detail"] == "high"
    assert message["image_url"].startswith("data:image/png;base64,")
    assert base64.b64decode(message["image_url"].split(",", 1)[1]).startswith(b"\x89PNG")


def test_no_consent_no_provider_call():
    c = fake_client()
    b = budget()
    with pytest.raises(VisualProviderError, match="consent"):
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=False, budget=b, client=c)
    c.responses.create.assert_not_called()
    assert b.calls_attempted == 0


def test_invalid_id_rejected_before_provider():
    c = fake_client()
    with pytest.raises(VisualProviderError, match="identifier"):
        analyze_visual_image(source_id="../../private", image_bytes=image_bytes(), consent=True, budget=budget(), client=c)
    c.responses.create.assert_not_called()


@pytest.mark.parametrize("invalid", [b"", b"not image", b"x" * (8 * 1024 * 1024 + 1)])
def test_invalid_image_fails_locally(invalid):
    c = fake_client()
    with pytest.raises(VisualProviderError):
        analyze_visual_image(source_id="docx_image_1", image_bytes=invalid, consent=True, budget=budget(), client=c)
    c.responses.create.assert_not_called()


def test_large_pixels_rejected_no_request():
    c = fake_client()
    with pytest.raises(VisualProviderError, match="pixel"):
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(4500,4500), consent=True, budget=budget(), client=c)
    c.responses.create.assert_not_called()


def test_resize_to_max_edge():
    c = fake_client()
    result = analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(3000,1000), consent=True, budget=budget(), client=c)
    assert result.width == 2048 and result.height <= 2048


def test_cost_preflight_blocks_call():
    c = fake_client()
    b = VisionBudget(max_estimated_usd=.001, input_price_per_million_usd=.4, output_price_per_million_usd=1.6)
    with pytest.raises(VisualProviderError, match="spending"):
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=b, client=c)
    c.responses.create.assert_not_called()


def test_call_cap_enforced():
    c = fake_client()
    b = budget(max_calls=1)
    for _ in range(1):
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=b, client=c)
    with pytest.raises(VisualProviderError, match="budget"):
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=b, client=c)
    assert c.responses.create.call_count == 1


@pytest.mark.parametrize("change", [
    {"source_id": "pdf_page_9"},
    {"unreadable_regions": "none"},
    {"visual_description": 5},
    {"extra": "unknown"},
])
def test_bad_response_schema_fails_closed(change):
    result = {"recognized_text": "ok", "visual_description": "a box", "unreadable_regions": [],
              "warnings": [], "source_id": "docx_image_1"}
    result.update(change)
    c = fake_client(result)
    b = budget()
    with pytest.raises(VisualProviderError, match="failed"):
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=b, client=c)
    assert b.stopped is True and b.calls_attempted == 1


def test_incomplete_provider_response_stops():
    c = fake_client(status="incomplete")
    b = budget()
    with pytest.raises(VisualProviderError, match="failed"):
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=b, client=c)
    assert b.stopped


def test_missing_usage_is_not_treated_as_free():
    c = fake_client(usage=False)
    b = budget()
    with pytest.raises(VisualProviderError):
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=b, client=c)
    assert b.estimated_spent_usd == pytest.approx(b.next_reservation_usd)
    assert b.stopped


def test_provider_exception_stops_and_is_sanitized():
    c = fake_client()
    c.responses.create.side_effect = RuntimeError("Sensitive content from request")
    b = budget()
    with pytest.raises(VisualProviderError) as exc:
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=b, client=c)
    assert "Sensitive" not in str(exc.value)
    assert b.stopped and b.calls_attempted == 1


def test_control_characters_annotated():
    c = fake_client({"recognized_text": "Title\u0012 Next", "visual_description": "diagram",
                     "unreadable_regions": [], "warnings": [], "source_id": "docx_image_1"})
    r = analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=budget(), client=c)
    assert "\u0012" not in r.recognized_text
    assert any("control characters" in w for w in r.warnings)


def test_budget_validation():
    with pytest.raises(VisualProviderError):
        budget(max_calls=11)
    with pytest.raises(VisualProviderError):
        budget(max_output_tokens=1201)


def test_no_text_without_uncertainty_fails():
    c = fake_client({"recognized_text": "", "visual_description": "", "unreadable_regions": [],
                     "warnings": [], "source_id": "docx_image_1"})
    with pytest.raises(VisualProviderError):
        analyze_visual_image(source_id="docx_image_1", image_bytes=image_bytes(), consent=True, budget=budget(), client=c)
