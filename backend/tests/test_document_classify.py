"""Stage-2 document classification tests (Jev via OpenRouter + fallback)."""

from __future__ import annotations

import pytest

from zellovest_workers.tasks.document_classify import (
    ClassificationResult,
    JevClassifyError,
    OpenRouterJevClassifier,
    _parse_jev_content,
    run_classification,
)


# --- OpenRouterJevClassifier._parse_jev_content ---


def test_parse_clean_json() -> None:
    """A clean JSON answer parses into a validated doc type + confidence."""
    doc_type, confidence = _parse_jev_content(
        '{"doc_type": "invoice", "confidence": 0.93}'
    )
    assert doc_type == "invoice"
    assert confidence == pytest.approx(0.93)


def test_parse_fenced_json() -> None:
    """Markdown-fenced answers parse via fence stripping."""
    content = '```json\n{"doc_type": "purchase_order", "confidence": 0.87}\n```'
    doc_type, confidence = _parse_jev_content(content)
    assert doc_type == "purchase_order"
    assert confidence == pytest.approx(0.87)


def test_parse_json_surrounded_by_prose() -> None:
    """Prose-wrapped JSON is recovered via brace scanning."""
    content = 'Sure! Here is my answer: {"doc_type": "contract", "confidence": 0.72}.'
    doc_type, _ = _parse_jev_content(content)
    assert doc_type == "contract"


def test_parse_document_type_alias() -> None:
    """Common variants/coercions map onto the canonical types."""
    doc_type, _ = _parse_jev_content('{"doc_type": "Purchase Order", "confidence": 0.8}')
    assert doc_type == "purchase_order"


def test_parse_confidence_clamped() -> None:
    """Out-of-range confidences clamp to [0, 1]."""
    _, high = _parse_jev_content('{"doc_type": "other", "confidence": 1.7}')
    assert high == 1.0
    _, low = _parse_jev_content('{"doc_type": "other", "confidence": -0.4}')
    assert low == 0.0


def test_parse_unknown_doc_type_raises() -> None:
    """An unrecognized type raises so the fallback path engages."""
    with pytest.raises(JevClassifyError):
        _parse_jev_content('{"doc_type": "receipt", "confidence": 0.9}')


# --- OpenRouterJevClassifier construction guards ---


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Construction fails fast without OPENROUTER_API_KEY."""

    class _Settings:
        jev_api_key = ""
        jev_api_url = "https://openrouter.ai/api/v1"
        jev_model = "openai/gpt-4o-mini"
        jev_timeout_seconds = 5.0

    monkeypatch.setattr(
        "zellovest_shared.config.get_settings", lambda: _Settings()
    )
    with pytest.raises(JevClassifyError):
        OpenRouterJevClassifier()


def test_classifier_builds_http_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """classify() posts an OpenRouter chat-completions request and parses."""

    class _Settings:
        jev_api_key = "test-key"
        jev_api_url = "https://openrouter.ai/api/v1/"
        jev_model = "openai/gpt-4o-mini"
        jev_timeout_seconds = 5.0

    monkeypatch.setattr(
        "zellovest_shared.config.get_settings", lambda: _Settings()
    )
    captured: dict = {}

    class _Response:
        status_code = 200

        @staticmethod
        def json() -> dict:
            return {
                "choices": [
                    {
                        "message": {
                            "content": '{"doc_type": "invoice", "confidence": 0.99}'
                        }
                    }
                ]
            }

    def _fake_post(url, *, json, headers, timeout):  # noqa: ANN001
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        return _Response()

    monkeypatch.setattr(
        "zellovest_workers.tasks.document_classify.httpx.post", _fake_post
    )
    result = OpenRouterJevClassifier().classify(
        extracted_text="INVOICE #123 amount due", filename="inv-1.pdf"
    )
    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert "INVOICE #123" in captured["json"]["messages"][1]["content"]
    assert result.doc_type == "invoice"
    assert result.confidence == pytest.approx(0.99)
    assert result.method == "jev_choice"


# --- run_classification fallback semantics ---


class _OkClassifier:
    """Classifier seam that always succeeds."""

    def __init__(self, result: ClassificationResult) -> None:
        self._result = result

    def classify(
        self, *, extracted_text: str, filename: str
    ) -> ClassificationResult:
        return self._result


class _FailingClassifier:
    """Classifier seam that always fails."""

    def classify(
        self, *, extracted_text: str, filename: str
    ) -> ClassificationResult:
        raise JevClassifyError("boom")


def test_run_classification_uses_injected_classifier() -> None:
    """A working classifier's result passes through unchanged (m=jev)."""
    result = run_classification(
        "invoice",
        "a.pdf",
        "invoice",
        classifier=_OkClassifier(
            ClassificationResult(
                doc_type="contract", confidence=0.81, method="jev_choice"
            )
        ),
    )
    assert result.doc_type == "contract"
    assert result.confidence == pytest.approx(0.81)
    assert result.method == "jev_choice"


def test_run_classification_falls_back_on_error() -> None:
    """A classifier failure degrades to keyword_fallback, not an exception."""
    result = run_classification(
        "purchase order po number 1234",
        "po.pdf",
        None,
        classifier=_FailingClassifier(),
    )
    assert result.doc_type == "purchase_order"
    assert result.method == "keyword_fallback"
    assert result.error == "boom"


def test_run_classification_fallback_uses_hint() -> None:
    """With no keywords and a valid hint, fallback honors the hint."""
    result = run_classification(
        "", "random.bin", "contract", classifier=_FailingClassifier()
    )
    assert result.doc_type == "contract"
    assert result.method == "keyword_fallback"


def test_run_classification_never_raises() -> None:
    """Any unexpected classifier error still yields a fallback result."""

    class _ExplodingClassifier:
        def classify(
            self, *, extracted_text: str, filename: str
        ) -> ClassificationResult:
            raise RuntimeError("logic bug")

    result = run_classification(
        "", "x.pdf", None, classifier=_ExplodingClassifier()
    )
    assert result.doc_type == "other"
    assert result.method == "keyword_fallback"
