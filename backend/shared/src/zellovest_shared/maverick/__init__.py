"""Maverick Spend detection package exports."""

from zellovest_shared.maverick.catalog_matcher import (
    find_approved_alternatives,
    index_software_catalog_item,
)
from zellovest_shared.maverick.feature_engineering import calculate_transaction_features
from zellovest_shared.maverick.groq_vendor import resolve_merchant_product
from zellovest_shared.maverick.jev_client import (
    evaluate_stage1_screening,
    evaluate_stage4_assessment,
)
from zellovest_shared.maverick.pipeline import process_transaction_maverick_spend

__all__ = [
    "calculate_transaction_features",
    "evaluate_stage1_screening",
    "evaluate_stage4_assessment",
    "find_approved_alternatives",
    "index_software_catalog_item",
    "process_transaction_maverick_spend",
    "resolve_merchant_product",
]
