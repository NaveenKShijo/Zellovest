"""Realistic multi-cohort SaaS telemetry generator for training and unseen-vendor tests.

Produces canonical HRIS user, seat assignment, SSO event, and contract feeds
across multiple renewal dates, company growth profiles, and tool usage cadences
so temporal cohort splitting and cross-vendor generalization can be validated
without data leakage.
"""

from __future__ import annotations

import argparse
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from zellovest_shared.logging_conf import get_logger

from zellovest_workers.ml.synthetic_ingest import synthetic_vendor_id
from zellovest_workers.ml.train_vertex import FEATURE_COLUMNS, TARGET_COLUMN

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """SaaS application profile governing pricing, penalty, and login cadence."""

    app_name: str
    category: str
    seat_cost_annual: float
    trueup_penalty_rate: float
    base_weekly_logins: float
    target_departments: tuple[str, ...]


TRAINING_CATALOG: tuple[ToolSpec, ...] = (
    ToolSpec(
        "salesforce", "Sales", 1800.0, 0.50, 5.5, ("Sales", "Marketing", "Customer Support")
    ),
    ToolSpec(
        "slack",
        "Collaboration",
        180.0,
        0.15,
        16.0,
        ("Engineering", "Sales", "Marketing", "Finance", "HR", "Operations"),
    ),
    ToolSpec(
        "zoom",
        "Communication",
        240.0,
        0.20,
        7.0,
        ("Engineering", "Sales", "Marketing", "Finance", "HR", "Operations"),
    ),
    ToolSpec("figma", "Design", 900.0, 0.40, 4.5, ("Engineering", "Marketing")),
    ToolSpec("github", "Engineering", 252.0, 0.25, 12.0, ("Engineering",)),
    ToolSpec("hubspot", "Marketing", 1200.0, 0.35, 4.0, ("Marketing", "Sales")),
    ToolSpec("docusign", "Operations", 480.0, 0.30, 0.9, ("Sales", "Finance", "HR")),
)

UNSEEN_INFERENCE_CATALOG: tuple[ToolSpec, ...] = (
    ToolSpec(
        "notion",
        "Collaboration",
        192.0,
        0.20,
        9.0,
        ("Engineering", "Marketing", "Operations", "HR"),
    ),
    ToolSpec("linear", "Engineering", 216.0, 0.25, 11.0, ("Engineering",)),
    ToolSpec("datadog", "Engineering", 1440.0, 0.45, 5.0, ("Engineering", "Operations")),
    ToolSpec("gong", "Sales", 1600.0, 0.40, 4.2, ("Sales",)),
    ToolSpec("carta", "Finance", 600.0, 0.30, 0.8, ("Finance", "HR")),
)

DEPARTMENTS: tuple[tuple[str, float, float], ...] = (
    # (name, share, annualized_base_churn)
    ("Engineering", 0.34, 0.08),
    ("Sales", 0.24, 0.24),
    ("Marketing", 0.15, 0.16),
    ("Operations", 0.12, 0.14),
    ("Finance", 0.08, 0.09),
    ("HR", 0.07, 0.11),
)


def _persona_retention_logit(
    persona: str,
    dept_churn: float,
    days_since_assigned: int,
    rng: np.random.Generator,
) -> float:
    """Compute realistic latent log-odds of active retention at renewal."""
    base = {"power": 2.8, "occasional": 1.1, "abandoning": -1.4, "zombie": -3.1}[persona]
    tenure_effect = 0.25 if days_since_assigned > 120 else -0.15
    churn_effect = -3.2 * dept_churn
    noise = float(rng.normal(0.0, 0.55))
    return base + tenure_effect + churn_effect + noise


def generate_company_telemetry(
    *,
    tenant_id: str,
    headcount: int,
    renewal_dates: tuple[date, ...],
    tools: tuple[ToolSpec, ...],
    growth_profile: str = "steady",
    seed: int = 47,
    reference_today: date | None = None,
) -> dict[str, pd.DataFrame]:
    """Generate realistic multi-renewal telemetry for one organization.

    Args:
        tenant_id: Target tenant identifier.
        headcount: Approximate active employee count.
        renewal_dates: Ordered contract renewal dates (historical or future).
        tools: Tool catalog specifications.
        growth_profile: One of ``high_growth``, ``steady``, or ``cost_cutting``.
        seed: Deterministic random seed.
        reference_today: Override for ``today`` when simulating events.

    Returns:
        Dictionary containing ``dim_users``, ``fact_seat_assignments``,
        ``fact_sso_events``, and ``dim_contracts`` DataFrames.
    """
    rng = np.random.default_rng(seed)
    today = reference_today or datetime.now(UTC).date()
    earliest_renewal = min(renewal_dates)
    latest_renewal = max(renewal_dates)
    sim_start = earliest_renewal - timedelta(days=480)
    event_end = min(today, latest_renewal + timedelta(days=7))

    growth_rate_bias = {"high_growth": 0.28, "steady": 0.08, "cost_cutting": -0.06}[growth_profile]
    dept_names = [item[0] for item in DEPARTMENTS]
    dept_probs = np.asarray([item[1] for item in DEPARTMENTS], dtype=np.float64)
    dept_churn_map = {item[0]: item[2] for item in DEPARTMENTS}

    users_rows: list[dict[str, Any]] = []
    assignment_rows: list[dict[str, Any]] = []
    event_rows: list[dict[str, Any]] = []
    contract_rows: list[dict[str, Any]] = []

    total_users = round(headcount * (1.25 if growth_profile == "high_growth" else 1.1))
    for idx in range(total_users):
        department = str(rng.choice(dept_names, p=dept_probs))
        # Spread hires across history including recent hires for growth signal.
        hire_offset = int(rng.integers(0, max((event_end - sim_start).days - 10, 30)))
        if growth_profile == "high_growth" and rng.random() < 0.45:
            low_offset = max((event_end - sim_start).days - 200, 1)
            high_offset = max((event_end - sim_start).days - 5, 2)
            hire_offset = int(rng.integers(low_offset, high_offset))
        hire_date = sim_start + timedelta(days=hire_offset)
        if hire_date > today:
            hire_date = today - timedelta(days=int(rng.integers(5, 60)))

        annual_churn = max(0.03, dept_churn_map[department] - growth_rate_bias * 0.12)
        termed = rng.random() < annual_churn * 1.15
        term_date: date | None = None
        status = "ACTIVE"
        if termed:
            max_span = max((event_end - hire_date).days, 15)
            term_date = hire_date + timedelta(days=int(rng.integers(14, max_span + 1)))
            if term_date <= today:
                status = "DEPROVISIONED"
            else:
                term_date = None

        user_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"bench:{tenant_id}:user:{idx}"))
        users_rows.append(
            {
                "user_id": user_id,
                "tenant_id": tenant_id,
                "email": f"emp.{idx}.{department.lower()}@{tenant_id}.example.com",
                "first_name": "Emp",
                "last_name": f"{idx}",
                "department": department,
                "hire_date": hire_date.isoformat(),
                "termination_date": term_date.isoformat() if term_date else None,
                "status": status,
                "employment_type": "FTE" if rng.random() < 0.88 else "CONTRACTOR",
            }
        )

    users_df = pd.DataFrame(users_rows)

    for tool_idx, tool in enumerate(tools):
        renewal_date = renewal_dates[tool_idx % len(renewal_dates)]
        app_id = f"app_{tool.app_name}_{tenant_id}"
        vendor_id = synthetic_vendor_id(tenant_id, tool.app_name)
        eligible = users_df[users_df["department"].isin(tool.target_departments)]
        assigned_count = 0

        for user in eligible.itertuples(index=False):
            if rng.random() > 0.78:
                continue
            u_hire = date.fromisoformat(str(user.hire_date))
            u_term = (
                date.fromisoformat(str(user.termination_date))
                if pd.notna(user.termination_date) and str(user.termination_date).strip()
                else None
            )
            assign_delay = int(rng.integers(0, 45))
            assigned_at = max(
                min(
                    u_hire + timedelta(days=assign_delay),
                    renewal_date - timedelta(days=35),
                ),
                u_hire,
            )
            if u_term is not None and assigned_at >= u_term:
                continue

            persona = str(
                rng.choice(
                    ["power", "occasional", "abandoning", "zombie"],
                    p=[0.42, 0.30, 0.16, 0.12],
                )
            )
            days_assigned = max((renewal_date - assigned_at).days, 1)
            logit = _persona_retention_logit(
                persona, dept_churn_map[str(user.department)], days_assigned, rng
            )
            retention_prob = 1.0 / (1.0 + float(np.exp(-logit)))
            will_stay_active = (u_term is None or u_term >= renewal_date) and (
                rng.random() < retention_prob
            )

            unassigned_at: date | None = None
            assign_status = "ACTIVE"
            if u_term is not None and u_term <= today:
                unassigned_at = u_term
                assign_status = "INACTIVE"

            assignment_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"bench:{tenant_id}:assign:{tool.app_name}:{user.user_id}",
                )
            )
            assignment_rows.append(
                {
                    "assignment_id": assignment_id,
                    "tenant_id": tenant_id,
                    "user_id": user.user_id,
                    "vendor_id": vendor_id,
                    "app_id": app_id,
                    "app_name": tool.app_name,
                    "department": user.department,
                    "assigned_at": assigned_at.isoformat(),
                    "unassigned_at": unassigned_at.isoformat() if unassigned_at else None,
                    "status": assign_status,
                    "persona": persona,
                    "zombie_cutoff": None,
                    "license_tier": "Enterprise" if tool.seat_cost_annual >= 900 else "Standard",
                }
            )
            assigned_count += 1

            # Generate daily SSO events from assigned_at up to min(event_end, u_term or event_end)
            active_end = min(event_end, u_term) if u_term else event_end
            window_days = (active_end - assigned_at).days
            if window_days <= 0:
                continue

            weekly_rate = tool.base_weekly_logins * (
                1.25 if persona == "power" else 0.55 if persona == "occasional" else 0.18
            )
            daily_lambda = weekly_rate / 7.0
            # Simulate progressive decay before renewal for churning/abandoning seats.
            if not will_stay_active:
                decay_days = int(rng.integers(35, 130))
                decay_start = max(assigned_at, renewal_date - timedelta(days=decay_days))
            else:
                decay_start = active_end + timedelta(days=30)

            for day_offset in range(window_days + 1):
                day = assigned_at + timedelta(days=day_offset)
                if day > today:
                    break
                effective_lambda = daily_lambda
                if persona == "abandoning" and day > assigned_at + timedelta(days=14):
                    effective_lambda *= 0.12
                elif day >= decay_start:
                    effective_lambda *= 0.04
                n_events = int(rng.poisson(effective_lambda))
                for evt_idx in range(min(n_events, 5)):
                    occurred = datetime.combine(day, datetime.min.time(), tzinfo=UTC) + timedelta(
                        hours=int(rng.integers(8, 19)),
                        minutes=int(rng.integers(0, 60)),
                    )
                    event_id = str(
                        uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"bench:{tenant_id}:{tool.app_name}:{user.user_id}:{day.isoformat()}:{evt_idx}",
                        )
                    )
                    event_rows.append(
                        {
                            "event_id": event_id,
                            "tenant_id": tenant_id,
                            "user_id": user.user_id,
                            "app_id": app_id,
                            "app_name": tool.app_name,
                            "department": user.department,
                            "occurred_at": occurred,
                            "event_type": "user.authentication.sso",
                            "outcome": "SUCCESS",
                        }
                    )

        contract_rows.append(
            {
                "tenant_id": tenant_id,
                "vendor_id": vendor_id,
                "app_id": app_id,
                "app_name": tool.app_name,
                "committed_seats": max(assigned_count, 1),
                "seat_cost_annual": tool.seat_cost_annual,
                "trueup_penalty_rate": tool.trueup_penalty_rate,
                "renewal_date": renewal_date.isoformat(),
                "category": tool.category,
            }
        )

    return {
        "dim_users": users_df,
        "fact_seat_assignments": pd.DataFrame(assignment_rows),
        "fact_sso_events": pd.DataFrame(event_rows),
        "dim_contracts": pd.DataFrame(contract_rows),
    }


def generate_multi_cohort_benchmark(
    *,
    num_training_tenants: int = 6,
    seed: int = 47,
    reference_today: date | None = None,
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    """Generate a multi-cohort training set and an unseen-vendor inference tenant."""
    today = reference_today or datetime.now(UTC).date()
    # Historical renewal cohorts spanning 15 months so temporal splits stay separated.
    historical_renewals = (
        today - timedelta(days=390),
        today - timedelta(days=300),
        today - timedelta(days=210),
        today - timedelta(days=120),
        today - timedelta(days=45),
    )
    profiles = ("steady", "high_growth", "cost_cutting")

    train_parts: dict[str, list[pd.DataFrame]] = {
        "dim_users": [],
        "fact_seat_assignments": [],
        "fact_sso_events": [],
        "dim_contracts": [],
    }
    for idx in range(num_training_tenants):
        tenant_id = f"bench_train_{idx + 1:02d}"
        data = generate_company_telemetry(
            tenant_id=tenant_id,
            headcount=120 + (idx % 3) * 60,
            renewal_dates=historical_renewals,
            tools=TRAINING_CATALOG,
            growth_profile=profiles[idx % len(profiles)],
            seed=seed + idx * 17,
            reference_today=today,
        )
        for key, df in data.items():
            train_parts[key].append(df)

    train_bundle = {key: pd.concat(parts, ignore_index=True) for key, parts in train_parts.items()}

    future_renewals = (
        today + timedelta(days=30),
        today + timedelta(days=60),
        today + timedelta(days=90),
        today + timedelta(days=120),
    )
    inference_bundle = generate_company_telemetry(
        tenant_id="default_org",
        headcount=160,
        renewal_dates=future_renewals,
        tools=UNSEEN_INFERENCE_CATALOG,
        growth_profile="high_growth",
        seed=seed + 999,
        reference_today=today,
    )
    return train_bundle, inference_bundle


def build_features_from_telemetry(
    bundle: dict[str, pd.DataFrame],
    *,
    horizons: tuple[int, ...] = (120, 90, 60, 30),
    reference_today: date | None = None,
) -> pd.DataFrame:
    """Mirror ``03_gold_seat_features.sql`` in Python for local training and backtests."""
    today = reference_today or datetime.now(UTC).date()
    users = bundle["dim_users"].copy()
    assignments = bundle["fact_seat_assignments"].copy()
    events = bundle["fact_sso_events"].copy()
    contracts = bundle["dim_contracts"].copy()

    users["hire_dt"] = pd.to_datetime(users["hire_date"]).dt.date
    users["term_dt"] = pd.to_datetime(users["termination_date"]).dt.date
    assignments["assigned_dt"] = pd.to_datetime(assignments["assigned_at"]).dt.date
    assignments["unassigned_dt"] = pd.to_datetime(assignments["unassigned_at"]).dt.date
    contracts["renewal_dt"] = pd.to_datetime(contracts["renewal_date"]).dt.date
    events["occurred_dt"] = pd.to_datetime(events["occurred_at"], utc=True).dt.tz_localize(None)

    user_lookup = users.set_index(["tenant_id", "user_id"])
    contract_lookup = contracts.set_index(["tenant_id", "app_name"])

    events_grouped: dict[tuple[str, str, str], np.ndarray] = {}
    for (t_id, u_id, a_name), grp in events.groupby(["tenant_id", "user_id", "app_name"]):
        events_grouped[(str(t_id), str(u_id), str(a_name))] = np.sort(
            grp["occurred_dt"].to_numpy(dtype="datetime64[s]")
        )

    rows: list[dict[str, Any]] = []
    for assign in assignments.itertuples(index=False):
        c_key = (str(assign.tenant_id), str(assign.app_name))
        if c_key not in contract_lookup.index:
            continue
        contract = contract_lookup.loc[c_key]
        if isinstance(contract, pd.DataFrame):
            contract = contract.iloc[0]
        renewal_dt: date = contract["renewal_dt"]
        u_key = (str(assign.tenant_id), str(assign.user_id))
        user_row = user_lookup.loc[u_key] if u_key in user_lookup.index else None
        dept = str(user_row["department"] if user_row is not None else assign.department)
        hire_dt: date = user_row["hire_dt"] if user_row is not None else assign.assigned_dt
        term_dt: date | None = (
            user_row["term_dt"] if user_row is not None and pd.notna(user_row["term_dt"]) else None
        )
        ev_arr = events_grouped.get(
            (str(assign.tenant_id), str(assign.user_id), str(assign.app_name))
        )
        app_cat = str(contract.get("category") or "Other")
        vendor_id = str(
            getattr(assign, "vendor_id", None) or contract.get("vendor_id") or assign.app_name
        )

        for horizon in horizons:
            as_of = renewal_dt - timedelta(days=horizon)
            if assign.assigned_dt > as_of:
                continue
            if pd.notna(assign.unassigned_dt) and assign.unassigned_dt <= as_of:
                continue
            if as_of > today:
                continue

            as_of_end = np.datetime64(
                datetime.combine(as_of + timedelta(days=1), datetime.min.time())
            )
            d30 = np.datetime64(datetime.combine(as_of - timedelta(days=30), datetime.min.time()))
            d60 = np.datetime64(datetime.combine(as_of - timedelta(days=60), datetime.min.time()))
            d90 = np.datetime64(datetime.combine(as_of - timedelta(days=90), datetime.min.time()))

            l30 = l60 = l90 = 0
            days_since_last = 9999
            if ev_arr is not None and len(ev_arr) > 0:
                window = ev_arr[(ev_arr >= d90) & (ev_arr < as_of_end)]
                l90 = len(window)
                l60 = int(np.sum(window >= d60))
                l30 = int(np.sum(window >= d30))
                if l90 > 0:
                    last_dt = pd.Timestamp(window[-1]).date()
                    days_since_last = max((as_of - last_dt).days, 0)

            label: int | None = None
            if renewal_dt <= today:
                r_end = np.datetime64(datetime.combine(renewal_dt, datetime.min.time()))
                r_start = np.datetime64(
                    datetime.combine(renewal_dt - timedelta(days=30), datetime.min.time())
                )
                post_count = 0
                if ev_arr is not None and len(ev_arr) > 0:
                    post_count = int(np.sum((ev_arr >= r_start) & (ev_arr < r_end)))
                active_hr = hire_dt <= renewal_dt and (term_dt is None or term_dt >= renewal_dt)
                label = int(active_hr and post_count >= 2)

            dept_lower = dept.casefold()
            cat_lower = app_cat.casefold()
            rows.append(
                {
                    "tenant_id": str(assign.tenant_id),
                    "employee_id": str(assign.user_id),
                    "vendor_id": vendor_id,
                    "app_name": str(assign.app_name),
                    "app_category": app_cat,
                    "department": dept,
                    "renewal_date": renewal_dt.isoformat(),
                    "renewal_horizon_days": horizon,
                    "feature_as_of_date": as_of.isoformat(),
                    "annual_seat_cost": float(contract["seat_cost_annual"]),
                    "trueup_penalty_rate": float(contract["trueup_penalty_rate"]),
                    "logins_30d": l30,
                    "logins_60d": l60,
                    "logins_90d": l90,
                    "days_since_last_login": days_since_last,
                    "login_momentum": (l30 / 30.0) / ((l90 / 90.0) + 1e-4),
                    "tenure_days": max((as_of - hire_dt).days, 0),
                    "days_since_assigned": max((as_of - assign.assigned_dt).days, 0),
                    "department_churn_rate": 0.0,
                    "department_growth_rate": 0.0,
                    "app_median_logins_30d": 0.0,
                    "relative_login_ratio": 0.0,
                    "department_engineering": int(
                        dept_lower in ("engineering", "product", "r&d")
                    ),
                    "department_sales": int(
                        dept_lower in ("sales", "revenue", "business development")
                    ),
                    "department_marketing": int(dept_lower in ("marketing", "growth")),
                    "department_finance": int(
                        dept_lower in ("finance", "accounting", "procurement")
                    ),
                    "department_hr": int(dept_lower in ("hr", "people", "hr & legal", "legal")),
                    "department_operations": int(
                        dept_lower in ("operations", "customer success", "support")
                    ),
                    "department_other": int(
                        dept_lower
                        not in (
                            "engineering", "product", "r&d", "sales", "revenue",
                            "business development", "marketing", "growth", "finance",
                            "accounting", "procurement", "hr", "people", "hr & legal",
                            "legal", "operations", "customer success", "support",
                        )
                    ),
                    "app_cat_sales": int(cat_lower in ("sales", "crm", "revenue")),
                    "app_cat_collaboration": int(
                        cat_lower in ("collaboration", "communication", "productivity")
                    ),
                    "app_cat_engineering": int(
                        cat_lower in ("engineering", "devtools", "infrastructure", "security")
                    ),
                    "app_cat_design": int(cat_lower in ("design", "creative")),
                    "app_cat_marketing": int(cat_lower in ("marketing", "analytics")),
                    "app_cat_other": int(
                        cat_lower
                        not in (
                            "sales", "crm", "revenue", "collaboration", "communication",
                            "productivity", "engineering", "devtools", "infrastructure",
                            "security", "design", "creative", "marketing", "analytics",
                        )
                    ),
                    TARGET_COLUMN: label,
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame

    # Compute app_median_logins_30d & relative_login_ratio per (tenant, vendor, horizon, as_of)
    medians = frame.groupby(
        ["tenant_id", "vendor_id", "renewal_horizon_days", "feature_as_of_date"]
    )["logins_30d"].transform("median")
    frame["app_median_logins_30d"] = medians.astype(float)
    frame["relative_login_ratio"] = (frame["logins_30d"] + 1e-3) / (
        frame["app_median_logins_30d"] + 1.0
    )

    # Compute department_churn_rate and department_growth_rate from HRIS snapshots.
    dept_snapshots = frame[["tenant_id", "department", "feature_as_of_date"]].drop_duplicates()
    churn_records: list[dict[str, Any]] = []
    for snap in dept_snapshots.itertuples(index=False):
        as_of_dt = date.fromisoformat(str(snap.feature_as_of_date))
        year_ago = as_of_dt - timedelta(days=365)
        dept_users = users[
            (users["tenant_id"] == snap.tenant_id) & (users["department"] == snap.department)
        ]
        hired_to_date = int((dept_users["hire_dt"] <= as_of_dt).sum())
        termed_1y = int(
            (
                dept_users["term_dt"].notna()
                & (dept_users["term_dt"] > year_ago)
                & (dept_users["term_dt"] <= as_of_dt)
            ).sum()
        )
        hired_1y = int(
            ((dept_users["hire_dt"] > year_ago) & (dept_users["hire_dt"] <= as_of_dt)).sum()
        )
        base_1y = int(
            (
                (dept_users["hire_dt"] <= year_ago)
                & (dept_users["term_dt"].isna() | (dept_users["term_dt"] > year_ago))
            ).sum()
        )
        churn_rate = (termed_1y / hired_to_date) if hired_to_date > 0 else 0.0
        growth_rate = ((hired_1y - termed_1y) / base_1y) if base_1y > 0 else 0.0
        growth_rate = max(-0.25, min(0.50, growth_rate))
        churn_records.append(
            {
                "tenant_id": snap.tenant_id,
                "department": snap.department,
                "feature_as_of_date": snap.feature_as_of_date,
                "department_churn_rate": churn_rate,
                "department_growth_rate": growth_rate,
            }
        )
    churn_df = pd.DataFrame(churn_records)
    frame = frame.drop(columns=["department_churn_rate", "department_growth_rate"]).merge(
        churn_df, on=["tenant_id", "department", "feature_as_of_date"], how="left"
    )
    for col in FEATURE_COLUMNS:
        if col not in frame.columns:
            frame[col] = 0.0
    return frame


def main() -> None:
    """CLI to generate multi-cohort benchmark Parquet datasets on disk."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--training-tenants", type=int, default=6)
    parser.add_argument("--seed", type=int, default=47)
    args = parser.parse_args()

    train_bundle, infer_bundle = generate_multi_cohort_benchmark(
        num_training_tenants=args.training_tenants,
        seed=args.seed,
    )
    train_dir = args.output_dir / "training"
    infer_dir = args.output_dir / "inference_unseen"
    train_dir.mkdir(parents=True, exist_ok=True)
    infer_dir.mkdir(parents=True, exist_ok=True)
    for name, df in train_bundle.items():
        df.to_parquet(train_dir / f"{name}.parquet", index=False)
    for name, df in infer_bundle.items():
        df.to_parquet(infer_dir / f"{name}.parquet", index=False)
    logger.info(
        "benchmark_datasets_generated",
        output_dir=str(args.output_dir),
        training_rows={k: len(v) for k, v in train_bundle.items()},
        inference_rows={k: len(v) for k, v in infer_bundle.items()},
    )


if __name__ == "__main__":
    main()
