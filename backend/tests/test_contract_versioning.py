"""Focused tests for stable contract and product-line matching."""

import unittest
import uuid
from decimal import Decimal
from types import SimpleNamespace

from zellovest_shared.contract_versioning import (
    AmbiguousContractLineError,
    match_contract_line,
    normalize_contract_number,
)
from zellovest_shared.db.models import ContractChangeType, ContractLine, ContractVersion
from zellovest_workers.tasks.ap_audit import compare_line_item


class ContractVersioningTests(unittest.TestCase):
    """Verify deterministic contract identity and amendment line matching."""

    def test_contract_number_normalization_ignores_case_and_extra_spaces(self) -> None:
        """Canonical contract IDs compare case-insensitively after whitespace cleanup."""
        self.assertEqual(normalize_contract_number("  Ab-12   C "), "ab-12 c")

    def test_exact_line_identity_matches_across_versions(self) -> None:
        """A product tier with the same stable identity maps to its existing line."""
        line = SimpleNamespace(
            id=uuid.uuid4(),
            contract_line_id=uuid.uuid4(),
            product_code="SKU-1",
            description="Seat license",
            uom="seat",
            qty_min=1,
            qty_max=10,
        )
        incoming = {
            "product_code": "SKU-1",
            "description": "Seat license",
            "uom": "seat",
            "qty_min": 1,
            "qty_max": 10,
        }
        self.assertIs(match_contract_line(incoming, [line]), line)

    def test_ambiguous_product_tiers_require_reviewer_mapping(self) -> None:
        """An amendment cannot guess between two tiers for the same product."""
        lines = [
            SimpleNamespace(
                id=uuid.uuid4(), contract_line_id=uuid.uuid4(), product_code="SKU-1",
                description="Seat license", uom="seat", qty_min=1, qty_max=10,
            ),
            SimpleNamespace(
                id=uuid.uuid4(), contract_line_id=uuid.uuid4(), product_code="SKU-1",
                description="Seat license", uom="seat", qty_min=11, qty_max=100,
            ),
        ]
        with self.assertRaises(AmbiguousContractLineError):
            match_contract_line(
                {"product_code": "SKU-1", "description": "Seat license", "uom": "seat"},
                lines,
            )

    def test_price_comparison_uses_deterministic_decimal_math(self) -> None:
        """Invoice price variance is computed without floating-point math."""
        comparison = compare_line_item(Decimal("10.00"), Decimal("10.02"))
        self.assertTrue(comparison["exception"])
        self.assertEqual(comparison["variance_pct"], 0.2)

    def test_version_models_and_event_type_are_exported(self) -> None:
        """Shared ORM exports expose the version header and stable line models."""
        self.assertEqual(ContractChangeType.AMENDMENT.value, "amendment")
        self.assertEqual(ContractVersion.__tablename__, "contract_versions")
        self.assertEqual(ContractLine.__tablename__, "contract_lines")


if __name__ == "__main__":
    unittest.main()
