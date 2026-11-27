"""Deterministic, penalty-aware optimization for SaaS seat commitments.

The independent Bernoulli retention predictions form a Poisson-binomial
demand distribution.  When departmental headcount growth is provided, net-new
seat demand is modeled as an independent Poisson increment and convolved
with the retained-seat PMF.  Exact convolution is deterministic and inexpensive
for the seat counts Zellovest targets, avoiding Monte Carlo instability in
financial recommendations.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

import numpy as np
from numpy.typing import NDArray


@dataclass(frozen=True, slots=True)
class ConfidenceInterval:
    """Integer retained-seat interval and its equivalent retention rates."""

    level: float
    lower_seats: int
    upper_seats: int
    lower_rate: float
    upper_rate: float


@dataclass(frozen=True, slots=True)
class DepartmentRetentionCurve:
    """A department's survival estimate at one renewal horizon."""

    department: str
    horizon_days: int
    assigned_seats: int
    expected_retained_seats: float
    survival_probability: float
    confidence_intervals: tuple[ConfidenceInterval, ...]
    expected_growth_seats: float = 0.0

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable representation for PostgreSQL JSONB."""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OptimizationResult:
    """Financial and demand outputs for one optimized seat cohort."""

    current_seats: int
    recommended_seats: int
    critical_fractile: float
    commitment_confidence: float
    expected_demand: float
    expected_shelfware_seats: float
    expected_trueup_seats: float
    shelfware_amount: float
    trueup_risk_amount: float
    savings_estimate: float
    demand_pmf: tuple[float, ...]
    departmental_curves: tuple[DepartmentRetentionCurve, ...]
    expected_retained_seats: float = 0.0
    expected_growth_seats: float = 0.0

    def to_dict(self, *, include_pmf: bool = False) -> dict[str, object]:
        """Return a JSON-safe result, optionally including the full demand PMF."""
        result = asdict(self)
        if not include_pmf:
            result.pop("demand_pmf", None)
        return result


def poisson_binomial_pmf(probabilities: Sequence[float]) -> NDArray[np.float64]:
    """Compute ``P(K=k)`` for independent, non-identical Bernoulli trials.

    Args:
        probabilities: Individual probabilities of retaining a seat.

    Returns:
        A length ``N + 1`` NumPy array whose entries sum to one.

    Raises:
        ValueError: If a probability is non-finite or outside ``[0, 1]``.
    """
    values: NDArray[np.float64] = np.asarray(probabilities, dtype=np.float64)
    if values.ndim != 1:
        raise ValueError("probabilities must be a one-dimensional sequence")
    if not np.all(np.isfinite(values)) or np.any((values < 0.0) | (values > 1.0)):
        raise ValueError("all retention probabilities must be finite and between 0 and 1")

    pmf: NDArray[np.float64] = np.array([1.0], dtype=np.float64)
    for probability in values:
        pmf = np.asarray(
            np.convolve(pmf, np.array([1.0 - probability, probability])),
            dtype=np.float64,
        )

    total = float(pmf.sum())
    if total <= 0.0 or not np.isfinite(total):
        raise ValueError("could not construct a valid demand distribution")
    return np.asarray(pmf / total, dtype=np.float64)


def poisson_growth_pmf(
    expected_growth_seats: float,
    *,
    tail_tolerance: float = 1e-9,
) -> NDArray[np.float64]:
    """Compute truncated Poisson PMF for projected net-new seat demand.

    Args:
        expected_growth_seats: Non-negative Poisson rate ``lambda``.
        tail_tolerance: Maximum discarded upper-tail probability mass.

    Returns:
        Normalized one-dimensional PMF array starting at 0 additional seats.
    """
    if not np.isfinite(expected_growth_seats) or expected_growth_seats < 0.0:
        raise ValueError("expected_growth_seats must be finite and non-negative")
    if expected_growth_seats == 0.0:
        return np.array([1.0], dtype=np.float64)

    lam = float(expected_growth_seats)
    max_k = max(math.ceil(lam + 10.0 * math.sqrt(lam) + 20.0), 1)
    weights: list[float] = []
    current = math.exp(-lam)
    cumulative = 0.0
    for k in range(max_k + 1):
        weights.append(current)
        cumulative += current
        if k >= lam and (1.0 - cumulative) <= tail_tolerance:
            break
        current = current * lam / float(k + 1)

    pmf = np.asarray(weights, dtype=np.float64)
    total = float(pmf.sum())
    if total <= 0.0 or not np.isfinite(total):
        raise ValueError("could not construct a valid growth demand distribution")
    return np.asarray(pmf / total, dtype=np.float64)


def newsvendor_critical_fractile(trueup_penalty_rate: float) -> float:
    """Return the contract's underage/overage critical fractile.

    The PRD formula is ``(1 + alpha) / (2 + alpha)``. Consequently, a higher
    true-up penalty can only increase the optimal commitment quantile.
    """
    if not np.isfinite(trueup_penalty_rate) or trueup_penalty_rate < 0.0:
        raise ValueError("trueup_penalty_rate must be finite and non-negative")
    return (1.0 + trueup_penalty_rate) / (2.0 + trueup_penalty_rate)


def _quantile_from_pmf(pmf: NDArray[np.float64], quantile: float) -> int:
    """Return the smallest integer demand whose CDF reaches ``quantile``."""
    if not 0.0 <= quantile <= 1.0:
        raise ValueError("quantile must be between 0 and 1")
    return min(int(np.searchsorted(np.cumsum(pmf), quantile, side="left")), len(pmf) - 1)


def _department_curves(
    probabilities: NDArray[np.float64],
    departments: Sequence[str] | None,
    horizon_days: int,
    *,
    expected_growth_rate: float = 0.0,
    growth_attach_rate: float = 1.0,
) -> tuple[DepartmentRetentionCurve, ...]:
    """Build exact 90% and 95% department retention and demand intervals."""
    grouped_probabilities: dict[str, list[float]] = {}
    if departments is not None and len(departments) != len(probabilities):
        raise ValueError("departments must contain one label per probability")
    for index, probability in enumerate(probabilities):
        department = "All" if departments is None else str(departments[index] or "Unassigned")
        grouped_probabilities.setdefault(department, []).append(float(probability))

    curves: list[DepartmentRetentionCurve] = []
    positive_growth = max(float(expected_growth_rate), 0.0) * float(growth_attach_rate)
    for department, values in sorted(grouped_probabilities.items()):
        department_probabilities: NDArray[np.float64] = np.asarray(values, dtype=np.float64)
        retained_pmf = poisson_binomial_pmf(values)
        seat_count = len(department_probabilities)
        dept_growth_seats = seat_count * positive_growth * (horizon_days / 365.0)
        if dept_growth_seats > 0.0:
            growth_pmf = poisson_growth_pmf(dept_growth_seats)
            pmf = np.asarray(np.convolve(retained_pmf, growth_pmf), dtype=np.float64)
            pmf = pmf / float(pmf.sum())
        else:
            pmf = retained_pmf
        intervals = tuple(
            ConfidenceInterval(
                level=level,
                lower_seats=_quantile_from_pmf(pmf, (1.0 - level) / 2.0),
                upper_seats=_quantile_from_pmf(pmf, 1.0 - ((1.0 - level) / 2.0)),
                lower_rate=(
                    _quantile_from_pmf(pmf, (1.0 - level) / 2.0) / seat_count if seat_count else 0.0
                ),
                upper_rate=(
                    _quantile_from_pmf(pmf, 1.0 - ((1.0 - level) / 2.0)) / seat_count
                    if seat_count
                    else 0.0
                ),
            )
            for level in (0.90, 0.95)
        )
        curves.append(
            DepartmentRetentionCurve(
                department=department,
                horizon_days=horizon_days,
                assigned_seats=seat_count,
                expected_retained_seats=round(float(department_probabilities.sum()), 4),
                survival_probability=round(float(department_probabilities.mean()), 6),
                confidence_intervals=intervals,
                expected_growth_seats=round(dept_growth_seats, 4),
            )
        )
    return tuple(curves)


def optimize_commitment(
    probabilities: Sequence[float],
    annual_seat_cost: float,
    trueup_penalty_rate: float,
    *,
    departments: Sequence[str] | None = None,
    horizon_days: int = 90,
    expected_growth_rate: float = 0.0,
    growth_attach_rate: float = 1.0,
) -> OptimizationResult:
    """Optimize the renewal commitment and quantify its expected financial risk.

    Args:
        probabilities: Per-assigned-seat probability of retention at renewal.
        annual_seat_cost: Annual contracted cost for one committed seat.
        trueup_penalty_rate: True-up surcharge as a decimal (``0.25`` = 25%).
        departments: Optional department label aligned to each probability.
        horizon_days: Renewal horizon represented by the predictions.
        expected_growth_rate: Annualized net headcount growth rate for the cohort.
        growth_attach_rate: Share of new hires expected to require a seat.

    Returns:
        A deterministic commitment, expected costs, PMF, and department curves.

    Raises:
        ValueError: If financial inputs, horizon, or probabilities are invalid.
    """
    if not np.isfinite(annual_seat_cost) or annual_seat_cost < 0.0:
        raise ValueError("annual_seat_cost must be finite and non-negative")
    if horizon_days <= 0:
        raise ValueError("horizon_days must be positive")
    if not np.isfinite(expected_growth_rate):
        raise ValueError("expected_growth_rate must be finite")
    if not np.isfinite(growth_attach_rate) or not 0.0 <= growth_attach_rate <= 1.0:
        raise ValueError("growth_attach_rate must be between 0 and 1")

    values: NDArray[np.float64] = np.asarray(probabilities, dtype=np.float64)
    retained_pmf = poisson_binomial_pmf(values.tolist())
    expected_retained = float(values.sum())
    positive_growth = max(float(expected_growth_rate), 0.0) * float(growth_attach_rate)
    expected_growth = len(values) * positive_growth * (horizon_days / 365.0)

    if expected_growth > 0.0:
        growth_pmf = poisson_growth_pmf(expected_growth)
        pmf = np.asarray(np.convolve(retained_pmf, growth_pmf), dtype=np.float64)
        pmf = pmf / float(pmf.sum())
    else:
        pmf = retained_pmf

    fractile = newsvendor_critical_fractile(trueup_penalty_rate)
    recommended = _quantile_from_pmf(pmf, fractile)
    demand: NDArray[np.float64] = np.arange(len(pmf), dtype=np.float64)
    shelfware_seats = float(np.dot(np.maximum(recommended - demand, 0.0), pmf))
    trueup_seats = float(np.dot(np.maximum(demand - recommended, 0.0), pmf))
    shelfware_amount = shelfware_seats * annual_seat_cost
    trueup_amount = trueup_seats * annual_seat_cost * (1.0 + trueup_penalty_rate)

    naive_trueup_seats = float(np.dot(np.maximum(demand - len(values), 0.0), pmf))
    baseline_expected_cost = (
        len(values) * annual_seat_cost
        + naive_trueup_seats * annual_seat_cost * (1.0 + trueup_penalty_rate)
    )
    optimized_expected_cost = recommended * annual_seat_cost + trueup_amount

    return OptimizationResult(
        current_seats=len(values),
        recommended_seats=recommended,
        critical_fractile=round(fractile, 8),
        commitment_confidence=round(float(np.cumsum(pmf)[recommended]), 8),
        expected_demand=round(expected_retained + expected_growth, 6),
        expected_shelfware_seats=round(shelfware_seats, 6),
        expected_trueup_seats=round(trueup_seats, 6),
        shelfware_amount=round(shelfware_amount, 2),
        trueup_risk_amount=round(trueup_amount, 2),
        savings_estimate=round(max(0.0, baseline_expected_cost - optimized_expected_cost), 2),
        demand_pmf=tuple(float(value) for value in pmf),
        departmental_curves=_department_curves(
            values,
            departments,
            horizon_days,
            expected_growth_rate=expected_growth_rate,
            growth_attach_rate=growth_attach_rate,
        ),
        expected_retained_seats=round(expected_retained, 6),
        expected_growth_seats=round(expected_growth, 6),
    )
