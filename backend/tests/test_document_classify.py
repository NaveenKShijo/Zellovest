"""Stage-2 document classification tests (Jev via OpenRouter Decisions API)."""

from __future__ import annotations

import pytest

from zellovest_workers.tasks.document_classify import (
    ClassificationResult,
    JevClassifyError,
    OpenRouterJevClassifier,
    run_classification,
)


# --- OpenRouterJevClassifier construction guards ---


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Construction fails fast without OPENROUTER_API_KEY."""

    class _Settings:
        jev_api_key = ""
        jev_api_url = "https://openrouter.ai/api/alpha/decisions"
        jev_model = "typesafe/jev-1.14"
        jev_timeout_seconds = 5.0

    monkeypatch.setattr(
        "zellovest_shared.config.get_settings", lambda: _Settings()
    )
    with pytest.raises(JevClassifyError):
        OpenRouterJevClassifier()


def test_classifier_builds_decisions_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """classify() posts Jev Decisions request (state + questions) and parses answer."""

    class _Settings:
        jev_api_key = "test-key"
        jev_api_url = "https://openrouter.ai/api/alpha/decisions/"
        jev_model = "typesafe/jev-1.14"
        jev_timeout_seconds = 5.0

    monkeypatch.setattr(
        "zellovest_shared.config.get_settings", lambda: _Settings()
    )
    captured: dict = {}

    class _Response:
        status_code = 200
        text = '{"answers": {"doc_type": {"type": "choice", "choice": "invoice", "confidence": 0.93}}}'

        @staticmethod
        def json() -> dict:
            return {
                "answers": {
                    "doc_type": {
                        "type": "choice",
                        "choice": "invoice",
                        "confidence": 0.93,
                        "probabilities": {
                            "invoice": 0.93,
                            "purchase_order": 0.04,
                            "contract": 0.02,
                            "other": 0.01,
                        },
                    }
                }
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
    assert captured["url"] == "https://openrouter.ai/api/alpha/decisions"
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    state = captured["json"]["state"]
    assert "INVOICE #123" in state["extracted_text"]
    assert state["filename"] == "inv-1.pdf"
    assert captured["json"]["questions"]["doc_type"]["type"] == "choice"
    assert "invoice" in captured["json"]["questions"]["doc_type"]["criteria"]
    assert result.doc_type == "invoice"
    assert result.confidence == pytest.approx(0.93)
    assert result.method == "jev_choice"


def test_classifier_rejects_non_choice_answer(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-choice answer type raises so fallback engages."""

    class _Settings:
        jev_api_key = "test-key"
        jev_api_url = "https://openrouter.ai/api/alpha/decisions"
        jev_model = "typesafe/jev-1.14"
        jev_timeout_seconds = 5.0

    monkeypatch.setattr(
        "zellovest_shared.config.get_settings", lambda: _Settings()
    )

    class _Response:
        status_code = 200
        text = '{"answers": {"doc_type": {"type": "choice", "choice": "invoice", "confidence": 0.93}}}'

        @staticmethod
        def json() -> dict:
            return {
                "answers": {
                    "doc_type": {
                        "type": "noul",
                        "noul": 0.5,
                    }
                }
            }

    def _fake_post(url, *, json, headers, timeout):  # noqa: ANN001
        return _Response()

    monkeypatch.setattr(
        "zellovest_workers.tasks.document_classify.httpx.post", _fake_post
    )
    with pytest.raises(JevClassifyError):
        OpenRouterJevClassifier().classify(
            extracted_text="text", filename="x.pdf"
        )


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
