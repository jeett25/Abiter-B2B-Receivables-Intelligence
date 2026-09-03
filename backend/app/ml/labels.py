from __future__ import annotations

import pandas as pd
from sqlalchemy.engine import Engine

from app.ml.config import (
    CLASS_BALANCE_HIGH,
    CLASS_BALANCE_LOW,
    CUMULATIVE_DAY_MARKS,
    HORIZON_DAYS,
)
from app.ml.features import (
    build_feature_table,
    invoice_static_features,
    load_raw_tables,
    organic_historical_mask,
    prior_issued_invoices,
    prior_resolved_invoices,
    rolling_features,
)
from app.models.enums import InvoiceStatus, PromiseStatus


def recovery_label(row, horizon_days: int = HORIZON_DAYS) -> int:
    """Training target: 1 iff paid within horizon_days of due_date. Written-off
    and paid-but-later-than-horizon both collapse to 0 -- this answers 'will it
    pay back within the window the business cares about', not 'ever'."""
    if row["status"] != InvoiceStatus.PAID.value:
        return 0
    delay = (row["paid_at"] - row["due_date"]).days
    return int(delay <= horizon_days)


def eventually_paid(row) -> int:
    """Diagnostic-only twin of recovery_label with no horizon cutoff. Never a
    training target or a feature -- exists so eval output can show the gap
    between 'recovered in time' and 'recovered eventually'."""
    return int(row["status"] == InvoiceStatus.PAID.value)


def root_cause_label(row) -> int:
    """Training target for the root-cause classifier: 1 = cash_flow_stress,
    0 = oversight. Deliberately 2-class, not 3-class -- 'dispute' is already
    a reliably observable business fact the Policy Gate reads directly via
    detect_dispute() (see app/decision/policy.py), so asking a model to
    re-predict it would be redundant and strictly less trustworthy than the
    ground-truth passthrough already in production. This label (and the
    table it's built from) is restricted to non-disputed rows only --
    build_root_cause_table() in train_root_cause.py filters those out before
    this ever runs, so 'dispute' should never reach this function."""
    assert row["true_root_cause"] != "dispute", "root_cause_label called on a disputed row"
    return int(row["true_root_cause"] == "cash_flow_stress")


def _curve_for_group(df: pd.DataFrame) -> dict:
    n = len(df)
    if n == 0:
        return {"n": 0, "written_off_rate": float("nan"), "cumulative_by_day": {d: float("nan") for d in CUMULATIVE_DAY_MARKS}}

    written_off_rate = (df["status"] == InvoiceStatus.WRITTEN_OFF.value).sum() / n
    cumulative_by_day = {}
    for d in CUMULATIVE_DAY_MARKS:
        recovered_by_d = ((df["status"] == InvoiceStatus.PAID.value) & (df["delay_days"] <= d)).sum()
        cumulative_by_day[d] = recovered_by_d / n
    return {"n": n, "written_off_rate": written_off_rate, "cumulative_by_day": cumulative_by_day}


def resolution_delay_curve(engine: Engine | None = None) -> dict:
    """Cumulative-resolved-by-N-days curve, pooled and broken out by archetype
    (read-only join, display/diagnostic only -- archetype is never a feature).
    Denominator is all historical (PAID+WRITTEN_OFF) invoices in the group, so
    cumulative_by_day[H] directly previews recovery_label's positive rate at
    horizon H -- not just delay-distribution among paid invoices."""
    tables = load_raw_tables(engine)
    invoices = tables["invoices"]
    payments = tables["payments"]
    customers = tables["customers"][["id", "archetype"]].rename(columns={"id": "customer_id"})

    hist = invoices[organic_historical_mask(invoices, payments)].merge(customers, on="customer_id", how="left")
    hist["delay_days"] = (hist["paid_at"] - hist["due_date"]).dt.days

    result = {"pooled": _curve_for_group(hist)}
    result["by_archetype"] = {name: _curve_for_group(group) for name, group in hist.groupby("archetype")}
    return result


def check_class_balance(curve: dict, horizon_days: int = HORIZON_DAYS) -> dict:
    """Pass/fail against the fixed 15%-85% bound. Only "pooled" gates the
    pipeline -- per-archetype heterogeneity is expected by construction (see
    CLASS_BALANCE_LOW/HIGH in config.py), so the per-archetype rates are still
    computed and returned for the printed diagnostic table but are informational
    only, never a reason to stop."""

    def _check(stats: dict) -> dict:
        rate = stats["cumulative_by_day"].get(horizon_days, float("nan"))
        return {"rate": rate, "passed": CLASS_BALANCE_LOW <= rate <= CLASS_BALANCE_HIGH}

    return {
        "pooled": _check(curve["pooled"]),
        "by_archetype": {name: _check(stats) for name, stats in curve["by_archetype"].items()},
    }


def _print_curve_and_checks(curve: dict, checks: dict) -> bool:
    def _print_group(label: str, stats: dict, check: dict, *, gates: bool) -> None:
        marks = ", ".join(f"{d}d={stats['cumulative_by_day'][d]:.1%}" for d in CUMULATIVE_DAY_MARKS)
        status = "PASS" if check["passed"] else ("FAIL" if gates else "info")
        print(
            f"  {label:<28} n={stats['n']:>5}  written_off={stats['written_off_rate']:.1%}  "
            f"{marks}  |  H={HORIZON_DAYS}d rate={check['rate']:.1%} [{status}]"
        )

    print(f"Class balance bound: [{CLASS_BALANCE_LOW:.0%}, {CLASS_BALANCE_HIGH:.0%}] at HORIZON_DAYS={HORIZON_DAYS}")
    print("(gates on pooled only -- per-archetype is a diagnostic, not a pass/fail gate)\n")
    print("Pooled (gates the pipeline):")
    _print_group("pooled", curve["pooled"], checks["pooled"], gates=True)
    print("\nBy archetype (diagnostic only):")
    for name in sorted(curve["by_archetype"]):
        _print_group(name, curve["by_archetype"][name], checks["by_archetype"][name], gates=False)
        if name == "strategic_enterprise" and not checks["by_archetype"][name]["passed"]:
            print(
                "    ^ known, accepted limitation: step-function delay distribution "
                "(~12% by day 60, ~92% by day 90) means no horizon lands this archetype in-band."
            )

    return checks["pooled"]["passed"]


def _eyeball_feature_table() -> None:
    table = build_feature_table()
    table["recovery_label"] = table.apply(recovery_label, axis=1)
    table["eventually_paid"] = table.apply(eventually_paid, axis=1)

    archetypes = load_raw_tables()["customers"][["id", "archetype"]].rename(columns={"id": "customer_id"})
    table = table.merge(archetypes, on="customer_id", how="left")

    print(f"\nFeature table: {len(table)} rows")
    print(f"recovery_label positive rate: {table['recovery_label'].mean():.1%}")
    print(f"eventually_paid positive rate: {table['eventually_paid'].mean():.1%}")

    cols = [
        "invoice_number", "due_date", "prior_invoice_count", "prior_payment_rate",
        "recent_90d_payment_rate", "recent_180d_payment_rate", "recovery_label",
    ]

    for archetype in ["chronic_late", "reliable_payer"]:
        candidates = table[table["archetype"] == archetype]
        if candidates.empty:
            continue
        best_customer = candidates.groupby("customer_id").size().idxmax()
        rows = candidates[candidates["customer_id"] == best_customer].sort_values("due_date")
        print(f"\n{archetype} customer {best_customer} ({len(rows)} invoices):")
        print(rows[cols].to_string(index=False))

    diverging = table.dropna(subset=["prior_payment_rate", "recent_90d_payment_rate"]).copy()
    if not diverging.empty:
        diverging["divergence"] = (diverging["prior_payment_rate"] - diverging["recent_90d_payment_rate"]).abs()
        top_customer = diverging.loc[diverging["divergence"].idxmax(), "customer_id"]
        rows = table[table["customer_id"] == top_customer].sort_values("due_date")
        print(f"\nLargest recency-vs-full-history divergence, customer {top_customer} ({rows['archetype'].iloc[0]}):")
        print(rows[cols].to_string(index=False))


def compute_promise_cutoffs(promises: pd.DataFrame, actions: pd.DataFrame) -> tuple[pd.Series, int]:
    """T = max(recovery_actions.timestamp) for the promise's own invoice -- proven
    exact given the generator's construction (promised_date is always set strictly
    after the ladder loop that produces every recovery_actions row for that
    invoice, so no action is ever dated after the promise it led to).

    Valid ONLY under today's one-promise-per-invoice generator invariant: this
    assigns the SAME T (the invoice's single last action) to every promise sharing
    an invoice_id, which is only correct because no invoice currently has more than
    one promise. It is not a general multi-promise solution -- if a future data
    source produces multiple promises per invoice, this reconstruction would need
    to change (e.g. each promise's own actions-up-to-its-creation-moment), and
    there isn't enough information in the current schema to do that reconstruction
    for multiple promises sharing one invoice's ladder.

    Fallback T = promised_date - 9d (midpoint of the generator's 3-15 day lead
    time) only applies if an invoice has a promise but zero recovery_actions rows
    -- per the invariant above this should never fire on today's dataset; the
    returned count makes that a checked fact, not just an assumption.
    """
    last_action_ts = actions.groupby("invoice_id")["timestamp"].max()
    fallback_count = 0
    cutoffs = []
    for _, promise in promises.iterrows():
        t = last_action_ts.get(promise["invoice_id"])
        if t is None or pd.isna(t):
            t = promise["promised_date"] - pd.Timedelta(days=9)
            fallback_count += 1
        cutoffs.append(t)
    return pd.Series(cutoffs, index=promises.index), fallback_count


def build_ptp_table(engine: Engine | None = None) -> pd.DataFrame:
    """One row per historical, terminal-status (KEPT/BROKEN) payment promise.
    Every feature -- both the promising invoice's own state (outstanding_ratio,
    amount-so-far, etc.) and the customer's rolling history -- is computed
    strictly as of T = compute_promise_cutoffs(), the same PriorResolved(C,t)
    mechanism used by build_feature_table(), just re-anchored to T instead of
    due_date.

    confidence_score is never loaded into this table -- it's generated as
    archetype.promise_keep_probability + small noise (confirmed in generator.py),
    a near-direct encoding of the hidden ground truth this model is trying to
    predict, not a candidate feature.

    Selection-bias caveat (reported, not fixed): promise occurrence correlates
    with archetype and escalation-ladder length, so this population skews toward
    harder-to-collect accounts relative to the full customer base. Realistic
    (production only ever observes promises actually made), but means any
    archetype-level comparison against this table must be restricted to the
    promise-eligible subpopulation, not the full customer base.
    """
    tables = load_raw_tables(engine)
    invoices = tables["invoices"]
    customers = tables["customers"].set_index("id")
    merchants = tables["merchants"].set_index("id")
    payments = tables["payments"]
    promises_all = tables["promises"]
    actions = tables["actions"]

    historical = invoices[organic_historical_mask(invoices, payments)]
    historical_indexed = historical.set_index("id", drop=False)
    by_customer = {cid: group for cid, group in historical.groupby("customer_id")}

    eligible_promises = promises_all[
        promises_all["invoice_id"].isin(historical_indexed.index)
        & promises_all["status"].isin([PromiseStatus.KEPT.value, PromiseStatus.BROKEN.value])
    ].copy()

    cutoffs, fallback_count = compute_promise_cutoffs(eligible_promises, actions)
    eligible_promises["T"] = cutoffs
    if fallback_count > 0:
        print(f"WARNING: T-reconstruction fallback fired {fallback_count} times -- investigate before trusting this table.")

    rows = []
    for _, promise in eligible_promises.iterrows():
        invoice_row = historical_indexed.loc[promise["invoice_id"]]
        customer_id = invoice_row["customer_id"]
        customer_row = customers.loc[customer_id]
        merchant_row = merchants.loc[customer_row["merchant_id"]]
        cutoff = promise["T"]
        group = by_customer[customer_id]

        prior_resolved = prior_resolved_invoices(group, invoice_row["id"], cutoff)
        prior_issued = prior_issued_invoices(group, invoice_row["id"], cutoff)

        row = {
            "promise_id": promise["id"],
            "invoice_id": invoice_row["id"],
            "customer_id": customer_id,
            "merchant_id": customer_row["merchant_id"],
            "T": cutoff,
            "promised_date": promise["promised_date"],
            "source": promise["source"],
            "kept": int(promise["status"] == PromiseStatus.KEPT.value),
        }
        row.update(invoice_static_features(invoice_row, customer_row, merchant_row, cutoff, payments))
        row.update(
            rolling_features(prior_resolved, prior_issued, promises_all, actions, cutoff, customer_row["relationship_start_date"])
        )
        rows.append(row)

    return pd.DataFrame(rows)


def _report_ptp_class_balance() -> None:
    """Same scrutiny as recovery_label's class-balance check, but no hard gate --
    just don't let 'row count, kept rate, fallback count' pass by unexamined,
    since the selection-bias caveat above means this population could plausibly
    skew far more than the recovery label's did."""
    table = build_ptp_table()
    print(f"\nPTP table: {len(table)} promises")

    kept_rate = table["kept"].mean()
    flag = "" if CLASS_BALANCE_LOW <= kept_rate <= CLASS_BALANCE_HIGH else "  <-- outside [15%, 85%], worth a look before training"
    print(f"kept positive rate (pooled): {kept_rate:.1%}{flag}")

    archetypes = load_raw_tables()["customers"][["id", "archetype"]].rename(columns={"id": "customer_id"})
    joined = table.merge(archetypes, on="customer_id", how="left")
    print("\nkept rate by archetype (promise-eligible subpopulation only, not the full customer base):")
    for name, group in joined.groupby("archetype"):
        rate = group["kept"].mean()
        flag = "" if CLASS_BALANCE_LOW <= rate <= CLASS_BALANCE_HIGH else "  <-- outside [15%, 85%]"
        print(f"  {name:<24} n={len(group):>4}  kept_rate={rate:.1%}{flag}")


if __name__ == "__main__":
    curve = resolution_delay_curve()
    checks = check_class_balance(curve)
    passed = _print_curve_and_checks(curve, checks)

    if not passed:
        print(
            f"\nTHRESHOLD FAILED -- pooled rate falls outside "
            f"[{CLASS_BALANCE_LOW:.0%}, {CLASS_BALANCE_HIGH:.0%}] at HORIZON_DAYS={HORIZON_DAYS}. "
            "Stopping here -- HORIZON_DAYS is not being changed automatically. "
            "Review the numbers above and decide how to proceed."
        )
    else:
        print("\nPooled threshold passed -- proceeding to feature-table eyeball.")
        _eyeball_feature_table()

    print("\n" + "=" * 80)
    print("PTP table diagnostic (independent of the recovery-label gate above)")
    print("=" * 80)
    _report_ptp_class_balance()
