"""Stage 2 — Jev AI document classification (typed Choice question).

Input : ``extracted_text`` (first ~4k chars, from the ``extraction_artifacts``
        row) plus the original filename.
Output: ``doc_type`` (invoice / purchase_order / contract / other) with a
        calibrated confidence in [0, 1], persisted onto the ``uploads`` row
        (``document_type`` / ``document_type_confidence`` /
        ``classification_method``) and into the artifact row's
        ``classification`` JSON for audit.

Transport: Jev (TypeSafe AI) is accessed through the OpenRouter
chat-completions API (``OPENROUTER_API_KEY``; model/URL configurable via
``JEV_MODEL`` / ``JEV_API_URL``). On any Jev failure the task falls back to
the existing keyword classifier (``document_ocr.classify_document``) so the
pipeline never stalls: the row keeps a usable doc type annotated with
``classification_method="keyword_fallback"``.

Execution model: ``process_document`` persists the extraction artifact, marks
the upload COMPLETED, then chains this task. Jev unavailability therefore
cannot fail an extraction — retries only re-refine classification.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from zellovest_shared.db.models import ExtractionArtifact
from zellovest_shared.db.models import Upload as UploadRow
from zellovest_shared.db.session import get_sync_engine
from zellovest_shared.logging_conf import get_logger
from zellovest_workers.celery_app import QUEUE_DOCUMENTS, celery_app

logger = get_logger(__name__)

DOCUMENT_TYPES: tuple[str, ...] = (
    "invoice",
    "purchase_order",
    "contract",
    "other",
)
CLASSIFICATION_SNIPPET_CHARS = 4000
_METHOD_JEV = "jev_choice"
_METHOD_FALLBACK = "keyword_fallback"

_SYSTEM_PROMPT = """\
You are Jev, TypeSafe AI's document classifier for Zellovest, an AI \
procurement platform.
Given a filename and the first characters of a document's extracted text, \
classify the document into exactly one of:
invoice, purchase_order, contract, other.

Rules:
- "invoice": bills, invoices, statements of amounts due, payment requests.
- "purchase_order": POs, requisitions, order confirmations.
- "contract": agreements, MSAs, SOWs, terms and conditions, renewals.
- "other": anything that does not clearly fit the above.

Respond ONLY with a JSON object of the exact shape:
{"doc_type": "<one of the four types>", "confidence": <number 0..1>}
"confidence" is your calibrated probability that the chosen type is correct.
"""


class JevClassifyError(Exception):
    """Raised when the Jev/OpenRouter classification call cannot be honored."""


@dataclass
class ClassificationResult:
    """Outcome of one Stage-2 classification decision.

    Attributes:
        doc_type: One of ``DOCUMENT_TYPES``.
        confidence: Calibrated probability in [0, 1].
        method: ``jev_choice`` | ``keyword_fallback``.
        model: Model id used (empty for the keyword fallback).
        raw_response: Raw model output excerpt (audit/debug).
        error: Failure detail when the method is ``keyword_fallback`` due
            to a Jev error; ``None`` on jev success.
    """

    doc_type: str
    confidence: float
    method: str
    model: str = ""
    raw_response: str = ""
    error: str | None = None


class DocumentClassifier(Protocol):
    """Test seam mirroring the ``DocumentAIClient`` pattern."""

    def classify(
        self, *, extracted_text: str, filename: str
    ) -> ClassificationResult:
        """Classify one document from text + filename.

        Args:
            extracted_text: First ~4k chars of the extracted document text.
            filename: Original filename (weak signal).

        Returns:
            A typed classification result.
        """
        ...


class OpenRouterJevClassifier:
    """Jev document classifier backed by the OpenRouter chat-completions API."""

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        """Initialize, defaulting every knob from shared settings.

        Args:
            api_url: OpenRouter API base URL (default ``JEV_API_URL``).
            api_key: OpenRouter API key (default ``OPENROUTER_API_KEY``).
            model: Chat model id (default ``JEV_MODEL``).
            timeout_seconds: Request timeout (default ``JEV_TIMEOUT_SECONDS``).

        Raises:
            JevClassifyError: When required settings are missing or invalid
                at construction time.
        """
        try:
            from zellovest_shared.config import get_settings

            settings = get_settings()
        except Exception as exc:  # pragma: no cover - settings misconfig
            raise JevClassifyError(f"settings unavailable: {exc}") from exc

        self._api_url = (
            api_url or settings.jev_api_url
        ).rstrip("/")
        self._api_key = api_key or settings.jev_api_key
        self._model = model or settings.jev_model
        self._timeout_seconds = (
            timeout_seconds or settings.jev_timeout_seconds
        )
        if not self._api_key:
            raise JevClassifyError("OPENROUTER_API_KEY is not configured")

    def classify(
        self, *, extracted_text: str, filename: str
    ) -> ClassificationResult:
        """Submit the typed Choice question to Jev via OpenRouter.

        Args:
            extracted_text: First ~4k chars of the extracted document text.
            filename: Original filename (weak signal).

        Returns:
            Parsed and validated classification result.

        Raises:
            JevClassifyError: On HTTP/auth errors, timeouts, or unparseable /
                invalid model output.
        """
        snippet = (extracted_text or "")[:CLASSIFICATION_SNIPPET_CHARS]
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"filename: {filename}\n\n"
                        "extracted_text (first "
                        f"{CLASSIFICATION_SNIPPET_CHARS} chars):\n{snippet}"
                    ),
                },
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Title": "Zellovest",
        }
        url = f"{self._api_url}/chat/completions"

        try:
            response = httpx.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise JevClassifyError(f"Jev request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise JevClassifyError(f"Jev request failed: {exc}") from exc

        if response.status_code != 200:
            raise JevClassifyError(
                f"Jev HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )
        try:
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise JevClassifyError(
                f"unexpected Jev response shape: {exc}"
            ) from exc

        doc_type, confidence = _parse_jev_content(content)
        return ClassificationResult(
            doc_type=doc_type,
            confidence=confidence,
            method=_METHOD_JEV,
            model=self._model,
            raw_response=content or "",
        )


def _extract_json_object(content: str) -> dict[str, Any]:
    """Extract the first JSON object from a model response string.

    Tolerates markdown fences and surrounding prose.

    Args:
        content: Raw assistant message content.

    Returns:
        Parsed JSON object.

    Raises:
        JevClassifyError: When no JSON object can be parsed.
    """
    if not content:
        raise JevClassifyError("empty Jev response")
    candidate = content.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()
    try:
        parsed = json.loads(candidate)
    except ValueError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise JevClassifyError(
                f"no JSON object in Jev response: {content[:200]!r}"
            )
        try:
            parsed = json.loads(candidate[start : end + 1])
        except ValueError as exc:
            raise JevClassifyError(
                f"unparseable Jev response: {exc}"
            ) from exc
    if not isinstance(parsed, dict):
        raise JevClassifyError("Jev response is not a JSON object")
    return parsed


def _normalize_doc_type(raw: Any) -> str:
    """Normalize and validate a model-provided document type.

    Args:
        raw: Raw value from the model JSON (any scalar).

    Returns:
        One of ``DOCUMENT_TYPES`` (camel/space/hyphen variants coerced).

    Raises:
        JevClassifyError: When the value maps to no known type.
    """
    value = str(raw or "").strip().lower()
    value = re.sub(r"[\s\-]+", "_", value)
    aliases = {
        "po": "purchase_order",
        "purchaseorder": "purchase_order",
        "contrat": "contract",
    }
    value = aliases.get(value, value)
    if value not in DOCUMENT_TYPES:
        raise JevClassifyError(f"unknown doc_type from Jev: {raw!r}")
    return value


def _parse_jev_content(content: str) -> tuple[str, float]:
    """Parse (doc_type, confidence) out of the Jev answer.

    Args:
        content: Raw assistant message content.

    Returns:
        Tuple of a valid document type and a confidence clamped to [0, 1]
        rounded to 4 decimals.

    Raises:
        JevClassifyError: On missing doc_type or unusable confidence.
    """
    parsed = _extract_json_object(content)
    raw_type = parsed.get("doc_type") or parsed.get("document_type")
    if raw_type is None:
        raise JevClassifyError("Jev response missing 'doc_type'")
    doc_type = _normalize_doc_type(raw_type)
    raw_conf = parsed.get("confidence")
    try:
        confidence = float(raw_conf)
    except (TypeError, ValueError) as exc:
        raise JevClassifyError(
            f"unusable confidence from Jev: {raw_conf!r}"
        ) from exc
    confidence = round(min(max(confidence, 0.0), 1.0), 4)
    return doc_type, confidence


def run_classification(
    extracted_text: str,
    filename: str,
    hint: str | None = None,
    *,
    classifier: DocumentClassifier | None = None,
) -> ClassificationResult:
    """Classify with Jev, falling back to the keyword classifier on failure.

    Args:
        extracted_text: First ~4k chars of the extracted document text.
        filename: Original filename.
        hint: Uploader-supplied document_type hint (used by the fallback).
        classifier: Injected Jev client; defaults to a real OpenRouter
            client (constructed lazily so missing config degrades to the
            fallback instead of raising).

    Returns:
        A ``ClassificationResult``; always non-throwing.
    """
    if classifier is None:
        try:
            classifier = OpenRouterJevClassifier()
        except JevClassifyError as exc:
            return _fallback_result("", hint, filename, str(exc))
    try:
        return classifier.classify(
            extracted_text=extracted_text, filename=filename
        )
    except JevClassifyError as exc:
        return _fallback_result(extracted_text, hint, filename, str(exc))
    except Exception as exc:  # defensive: client bugs never stall stage 2
        return _fallback_result(extracted_text, hint, filename, str(exc))


def _fallback_result(
    extracted_text: str,
    hint: str | None,
    filename: str,
    error: str,
) -> ClassificationResult:
    """Produce a keyword-fallback ``ClassificationResult``.

    Args:
        extracted_text: Extracted text (keyword classifier input).
        hint: Uploader-supplied document_type hint.
        filename: Original filename.
        error: Why Jev was not used (logged + stored for audit).

    Returns:
        ClassificationResult with ``method="keyword_fallback"``.
    """
    from zellovest_workers.tasks.document_ocr import classify_document

    doc_type, confidence = classify_document(
        extracted_text, hint=hint, filename=filename
    )
    logger.warning("jev_classify_failed", error_class="JevClassifyError", error=error)
    return ClassificationResult(
        doc_type=doc_type,
        confidence=round(min(max(confidence, 0.0), 1.0), 4),
        method=_METHOD_FALLBACK,
        raw_response="",
        error=error,
    )


def _build_provenance(result: ClassificationResult, filename: str) -> dict[str, Any]:
    """Build the PRD §8 provenance entry for the classification decision.

    Args:
        result: Classification outcome to record.
        filename: Source document name.

    Returns:
        Provenance dict mirroring ``document_ocr._build_provenance``.
    """
    return {
        "field": "document_type",
        "value": result.doc_type,
        "confidence": result.confidence,
        "source_document": filename,
        "page": 0,
        "bounding_box": [],
        "extraction_method": result.method,
        "extracted_at": datetime.now(UTC).isoformat(),
        "model": result.model,
        "error": result.error,
    }


def _load_inputs(upload_id: str) -> tuple[UploadRow | None, ExtractionArtifact | None]:
    """Load the upload lease and artifact rows for classification.

    Args:
        upload_id: Upload row id string.

    Returns:
        Tuple of (upload row, artifact row); either may be ``None``.
    """
    engine = get_sync_engine()
    with Session(engine) as session:
        try:
            key = uuid.UUID(upload_id)
        except ValueError:
            return None, None
        try:
            upload = session.get(UploadRow, key)
            artifact = session.execute(
                select(ExtractionArtifact).where(ExtractionArtifact.upload_id == key)
            ).scalar_one_or_none()
        except Exception as exc:
            # e.g. migration 0013 not applied yet; degrade to "skipped"
            logger.warning(
                "document_classification_load_failed",
                upload_id=upload_id,
                error_class=type(exc).__name__,
            )
            return None, None
        return upload, artifact


def _apply_classification(
    upload_id: str,
    result: ClassificationResult,
    provenance: dict[str, Any],
    fallback_filename: str,
) -> None:
    """Persist the Stage-2 decision (never fails the task).

    Updates ``uploads`` (document_type/_confidence/classification_method)
    and appends the decision to the artifact row's ``classification`` JSON.

    Args:
        upload_id: Upload row id string.
        result: Classification outcome.
        provenance: PRD §8 provenance entry for the decision.
        fallback_filename: Filename when no artifact row exists.
    """
    try:
        engine = get_sync_engine()
        with Session(engine) as session:
            try:
                key = uuid.UUID(upload_id)
            except ValueError:
                return
            upload = session.get(UploadRow, key)
            if upload is not None:
                upload.document_type = result.doc_type
                upload.document_type_confidence = result.confidence
                upload.classification_method = result.method
            artifact = session.execute(
                select(ExtractionArtifact).where(
                    ExtractionArtifact.upload_id == key
                )
            ).scalar_one_or_none()
            if artifact is not None:
                previous = dict(artifact.classification) if artifact.classification else {}
                history = list(previous.get("history", []))
                if previous:
                    history.append(
                        {
                            "document_type": previous.get("document_type"),
                            "method": previous.get("method"),
                            "classified_at": previous.get("classified_at"),
                        }
                    )
                artifact.classification = {
                    "document_type": result.doc_type,
                    "confidence": result.confidence,
                    "method": result.method,
                    "model": result.model,
                    "source_document": (
                        provenance.get("source_document") or fallback_filename
                    ),
                    "classified_at": provenance.get("extracted_at", ""),
                    "history": history[-9:],
                }
            session.commit()
    except Exception as exc:
        logger.warning(
            "document_classification_apply_failed",
            upload_id=upload_id,
            error_class=type(exc).__name__,
        )


@celery_app.task(
    name="zellovest.workers.tasks.document_classify.classify_upload",
    queue=QUEUE_DOCUMENTS,
    max_retries=3,
)
def classify_upload(
    tenant_id: str,
    upload_id: str,
    filename: str = "",
    hint: str | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Stage-2 task: Jev Choice classification for one processed upload.

    Reads the first ~4k chars of extracted text from the
    ``extraction_artifacts`` row (pure Postgres read; no GCS I/O), runs the
    Jev classifier with keyword fallback, and persists
    (doc_type, confidence, method) onto the ``uploads`` row plus the
    artifact's ``classification`` JSON.

    Args:
        tenant_id: Owning tenant.
        upload_id: Upload row id (as string).
        filename: Original filename (weak signal for classification).
        hint: Uploader-supplied document_type hint (fallback input).
        **kwargs: Ignored extras for forward compatibility.

    Returns:
        Dict with doc_type, confidence, method, and status.
    """
    upload, artifact = _load_inputs(upload_id)
    if upload is None:
        logger.warning(
            "document_classification_no_upload",
            tenant_id=tenant_id,
            upload_id=upload_id,
        )
        return {
            "tenant_id": tenant_id,
            "upload_id": upload_id,
            "status": "skipped",
            "error": "upload row not found",
        }

    effective_filename = filename or upload.filename
    if artifact is None or artifact.text_snippet is None:
        logger.warning(
            "document_classification_inputs_missing",
            tenant_id=tenant_id,
            upload_id=upload_id,
        )
        return {
            "tenant_id": tenant_id,
            "upload_id": upload_id,
            "status": "skipped",
            "error": "extraction artifact row missing",
        }

    result = run_classification(
        artifact.text_snippet,
        effective_filename,
        hint,
    )
    provenance = _build_provenance(result, effective_filename)
    _apply_classification(upload_id, result, provenance, effective_filename)

    logger.info(
        "document_classified",
        tenant_id=tenant_id,
        upload_id=upload_id,
        doc_type=result.doc_type,
        confidence=result.confidence,
        classification_method=result.method,
        model=result.model,
    )
    return {
        "tenant_id": tenant_id,
        "upload_id": upload_id,
        "document_type": result.doc_type,
        "confidence": result.confidence,
        "classification_method": result.method,
        "status": "completed",
    }
