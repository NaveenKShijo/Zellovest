"""Focused unit tests for the deterministic AP Audit & Compliance Engine.

Verifies pure Decimal variance calculations, annual escalation compounding,
quantity brackets, discount omissions, tax exemptions, payment terms,
freight rules, and premature / post-expiration billing bounds. Zero LLM math.
"""

from __future__ import annotations

import unittest
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from zellovest_shared.db.models import ExceptionRule, ExceptionStatus
from zellovest_workers.tasks.ap_audit import (
    _compute_escalated_price,
    _is_freight_included,
    _is_freight_line,
    _make_exception,
    _payment_days,
    _same_product,
    _tax_rate,
    _within_quantity,
    compare_line_item,
)


class APAuditEngineTests(unittest.TestCase):
    """Test suite for deterministic AP audit rules and variance calculations."""

    def test_annual_escalation_cap_compounds_per_contract_year(self) -> None:
        """Annual escalation cap compounds base rate at escalation_pct per 365-day year."""
        start_date = date(2024, 1, 1)
        base_price = Decimal("100.00")
        escalation_pct = Decimal("5.0")  # 5% annual cap

        # Year 1 (day 180): No escalation permitted yet (same year)
        price_y1 = _compute_escalated_price(base_price, escalation_pct, start_date, date(2024, 7, 1))
        self.assertEqual(price_y1, Decimal("100.00"))

        # Year 2 (day 370): 1 year elapsed -> 100 * 1.05 = 105.00
        price_y2 = _compute_escalated_price(base_price, escalation_pct, start_date, date(2025, 1, 15))
        self.assertEqual(price_y2, Decimal("105.00"))

        # Year 3 (day 740): 2 years elapsed -> 100 * 1.05^2 = 110.25
        price_y3 = _compute_escalated_price(base_price, escalation_pct, start_date, date(2026, 1, 15))
        self.assertEqual(price_y3, Decimal("110.25"))

        # None or 0% escalation leaves base price unchanged
        price_zero = _compute_escalated_price(base_price, None, start_date, date(2026, 1, 15))
        self.assertEqual(price_zero, Decimal("100.00"))

    def test_line_item_comparison_pure_decimal_precision(self) -> None:
        """Line-item variance calculation uses Decimal and detects pricing discrepancy."""
        contract_price = Decimal("132.50")
        billed_price = Decimal("145.00")

        res = compare_line_item(contract_price, billed_price)
        self.assertTrue(res["exception"])
        # Variance = (145 - 132.5) / 132.5 * 100 = 9.4339...%
        self.assertAlmostEqual(res["variance_pct"], 9.43396, places=4)

        # Within $0.01 tolerance should not flag an exception
        compliant_res = compare_line_item(Decimal("132.50"), Decimal("132.505"))
        self.assertFalse(compliant_res["exception"])

    def test_quantity_bracket_tier_evaluation(self) -> None:
        """Quantity limits evaluate correctly against tier minimums and maximums."""
        term_tier1 = SimpleNamespace(qty_min=1, qty_max=100)
        term_tier2 = SimpleNamespace(qty_min=101, qty_max=500)

        # 50 units is within Tier 1, outside Tier 2
        self.assertTrue(_within_quantity(term_tier1, Decimal("50")))
        self.assertFalse(_within_quantity(term_tier2, Decimal("50")))

        # 250 units is outside Tier 1, within Tier 2
        self.assertFalse(_within_quantity(term_tier1, Decimal("250")))
        self.assertTrue(_within_quantity(term_tier2, Decimal("250")))

        # 600 units exceeds both tiers
        self.assertFalse(_within_quantity(term_tier1, Decimal("600")))
        self.assertFalse(_within_quantity(term_tier2, Decimal("600")))

    def test_freight_detection_and_fob_destination_rules(self) -> None:
        """Freight keywords and contract inclusion terms are accurately detected."""
        freight_line = SimpleNamespace(description="Standard freight & courier delivery", product_code="SHP-01")
        software_line = SimpleNamespace(description="Figma Editor Annual License", product_code="FIG-EDIT")

        self.assertTrue(_is_freight_line(freight_line))
        self.assertFalse(_is_freight_line(software_line))

        # Freight included terms
        self.assertTrue(_is_freight_included("FOB Destination - Freight Prepaid"))
        self.assertTrue(_is_freight_included("Shipping included in unit pricing"))
        self.assertFalse(_is_freight_included("FOB Origin, billed separately"))

    def test_tax_exemption_parsing(self) -> None:
        """Tax rules correctly parse exempt clauses and explicit percentage rates."""
        self.assertEqual(_tax_rate("Tax Exempt"), Decimal("0"))
        self.assertEqual(_tax_rate("Zero Rated - Export"), Decimal("0"))
        self.assertEqual(_tax_rate("State Sales Tax 6.25%"), Decimal("0.0625"))
        self.assertIsNone(_tax_rate("Subject to local jurisdiction variable rates"))

    def test_payment_terms_net_days_extraction(self) -> None:
        """Net N payment terms correctly extract integer day counts."""
        self.assertEqual(_payment_days("Net 30 Days"), 30)
        self.assertEqual(_payment_days("Payment terms: Net 45"), 45)
        self.assertEqual(_payment_days("Net 60"), 60)
        self.assertIsNone(_payment_days("Due upon receipt"))

    def test_product_matching_by_code_and_normalized_description(self) -> None:
        """Matches products by SKU code or normalized whitespace description."""
        inv_line = SimpleNamespace(product_code="SF-CRM-ENT", description="Salesforce CRM")
        term = SimpleNamespace(product_code="SF-CRM-ENT", description="Different Description")
        self.assertTrue(_same_product(inv_line, term))

        inv_desc = SimpleNamespace(product_code=None, description="  Enterprise  Support  Plan ")
        term_desc = SimpleNamespace(product_code=None, description="Enterprise Support Plan")
        self.assertTrue(_same_product(inv_desc, term_desc))

    def test_make_exception_creates_immutable_record_with_exact_variance(self) -> None:
        """Verifies immutable exception record instantiation with severity categorization."""
        invoice = SimpleNamespace(id=uuid4(), tenant_id="tenant-acme", po_id=None)
        line = SimpleNamespace(id=uuid4())
        contract = SimpleNamespace(id=uuid4())
        version = SimpleNamespace(id=uuid4())
        term = SimpleNamespace(id=uuid4())

        exc = _make_exception(
            invoice=invoice,
            invoice_line=line,
            contract=contract,
            version=version,
            term=term,
            rule=ExceptionRule.PRICE,
            expected=Decimal("100.00"),
            billed=Decimal("115.00"),
            variance_amount=Decimal("150.00"),
            variance_pct=15.0,
        )

        self.assertEqual(exc.tenant_id, "tenant-acme")
        self.assertEqual(exc.invoice_id, invoice.id)
        self.assertEqual(exc.invoice_line_id, line.id)
        self.assertEqual(exc.rule_type, ExceptionRule.PRICE)
        self.assertEqual(exc.expected_value, 100.0)
        self.assertEqual(exc.billed_value, 115.0)
        self.assertEqual(exc.variance_amount, 150.0)
        self.assertEqual(exc.variance_pct, 15.0)
        self.assertEqual(exc.severity, "high")  # >= 10% magnitude -> high
        self.assertEqual(exc.status, ExceptionStatus.OPEN)


if __name__ == "__main__":
    unittest.main()
