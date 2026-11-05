"""Pure helpers for deterministic contract and product-line matching."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Sequence


class AmbiguousContractLineError(ValueError):
    """Raised when extracted amendment terms could map to multiple lines."""


def normalize_contract_number(value: str | None) -> str:
    """Normalize whitespace and letter case while preserving identifier punctuation."""
    return " ".join((value or "").split()).casefold()


def _text(value: Any) -> str:
    """Normalize a nullable string for exact matching."""
    return " ".join(str(value or "").split()).casefold()


def _decimal(value: Any) -> Decimal | None:
    """Convert an optional numeric term value to a stable Decimal."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value)).normalize()
    except (InvalidOperation, ValueError, TypeError):
        return None


def term_line_key(term: Mapping[str, Any] | Any) -> tuple[str, str, Decimal | None, Decimal | None, str]:
    """Return the product/tier identity used to match term rows across versions."""
    get = term.get if isinstance(term, Mapping) else lambda key, default=None: getattr(term, key, default)
    product_code = _text(get("product_code"))
    description = _text(get("description"))
    return (
        product_code,
        _text(get("uom")),
        _decimal(get("qty_min")),
        _decimal(get("qty_max")),
        description if not product_code else "",
    )


def match_contract_line(
    incoming: Mapping[str, Any],
    existing_lines: Sequence[Any],
) -> Any | None:
    """Match an extracted term to one existing line, or return ``None`` if new.

    Exact product/tier identity is preferred. A single existing line with the
    same product code can represent an amended quantity tier. Multiple possible
    matches require a reviewer to choose explicitly.
    """
    explicit_id = incoming.get("contract_line_id")
    if explicit_id:
        matches = [line for line in existing_lines if str(line.id) == str(explicit_id)]
        if not matches:
            raise AmbiguousContractLineError("Selected product line is not part of the parent contract.")
        return matches[0]

    incoming_key = term_line_key(incoming)
    exact = [line for line in existing_lines if term_line_key(line) == incoming_key]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise AmbiguousContractLineError("More than one contract line matches the extracted product tier.")

    product_code = incoming_key[0]
    if product_code:
        same_product = [line for line in existing_lines if _text(line.product_code) == product_code]
    else:
        description = incoming_key[4]
        same_product = [line for line in existing_lines if _text(line.description) == description]
    if len(same_product) == 1:
        return same_product[0]
    if len(same_product) > 1:
        raise AmbiguousContractLineError(
            "The amendment line matches multiple pricing tiers; select the parent line in review."
        )
    return None
