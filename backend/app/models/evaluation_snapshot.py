from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class EvaluationSnapshot(Base):
    """Current-snapshot overwrite (one row per strategy_name -- "Baseline
    (email everyone)" / "Decision engine"), same category of table as
    account_state: it holds the LATEST precomputed baseline-vs-engine
    comparison, not an append-only history.

    Why this table exists (Day 6 bug, see app/api/DECISIONS.md): GET
    /api/metrics used to derive this comparison at request time from
    persisted account_state.next_action/recoverability_score across every
    invoice ever scored -- including ones a later mutation (Day 5's
    attribution write-back) had already resolved, and using economics that
    had since been corrected (Day 5's ESCALATE fix) after those next_action
    values were chosen. Recomputing today's economics against yesterday's
    action choices produced an internally-inconsistent, falsely negative
    number. A genuinely fresh run (app.decision.service.run_full_live_pass(),
    re-deciding every currently-open invoice under CURRENT economics) gives
    the honest, self-consistent answer -- but takes ~55s, too slow for a
    page load. This table is that fresh result, computed once via
    `python -m app.decision.persist_evaluation` and re-run whenever the live
    pool or the economics config changes (same operational pattern as
    attribution_experiment_results)."""

    __tablename__ = "evaluation_snapshots"

    strategy_name: Mapped[str] = mapped_column(String(100), primary_key=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    n_invoices: Mapped[int] = mapped_column(Integer, nullable=False)
    n_interventions: Mapped[int] = mapped_column(Integer, nullable=False)
    n_wait: Mapped[int] = mapped_column(Integer, nullable=False)
    n_stop: Mapped[int] = mapped_column(Integer, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    gross_expected_recovered: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_friction: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    net_expected_recovered: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    recovery_rate: Mapped[float] = mapped_column(nullable=False)
    unnecessary_interventions_avoided: Mapped[int] = mapped_column(Integer, nullable=False)
