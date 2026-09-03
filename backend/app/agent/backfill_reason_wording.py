"""One-off maintenance script (2026-09-03): cleans up decision_logs.reason
text written before two viewer-facing wording fixes landed. Neither the
regular pipeline (app.agent.final_integration_pass, synthetic.seed_demo)
nor a fresh git pull touches these -- decision_logs is append-only, and
both fixes are about historical audit-trail TEXT, not anything the normal
pipeline recomputes. Run this once per database that predates the fixes
(this work PC's DB already had it applied manually; any other database --
home Mac, Supabase -- needs this run explicitly).

1. Closing entries (app/attribution/persist.py's build_closing_decision_log,
   written when an invoice is recovered via the attribution experiment's
   ledger write-back) used to name "Day-5", an internal build-day reference
   meaningless to anyone reading the UI without repo context.
   CLOSING_ENTRY_MARKER is now generic ("randomized control-group
   experiment"). See CLAUDE.md's "⚠ CURRENT CANONICAL STATE" section.
2. Tool-failure fallback entries (app/agent/nodes.py's dispatch_action)
   used to splice the raw vendor error message (e.g. a real Razorpay API
   exception string) directly into decision_logs.reason -- shown verbatim
   on "Why this decision?"/Policy Gate/Timeline. Now a clean, generic
   sentence; the raw message is still available via
   policy_checks.tool_result.message (shown de-emphasized in Safety &
   Failure Handling), never lost, just not the headline.

Idempotent / safe to rerun: only rows still matching the OLD text/pattern
get touched -- a rerun after the fix is already applied updates 0 rows.

Run with: python -m app.agent.backfill_reason_wording
"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.core.db import SessionLocal
from app.models import DecisionLog

_OLD_CLOSING_REASON = (
    "Invoice recovered via the Day-5 attribution experiment's randomized-holdout simulation, not a fresh "
    "decision-engine assessment -- the entries above reflect the last real decision made before this "
    "payment was recorded."
)
_NEW_CLOSING_REASON = (
    "Invoice recovered as part of a randomized control-group experiment, not a fresh decision-engine "
    "assessment -- the entries above reflect the last real decision made before this payment was recorded."
)

# Matches ONLY the old "<action> failed after <n> attempt(s): <raw message>"
# shape (colon-separated) -- the new shape uses a comma instead
# ("... attempt(s), fell back to wait"), so an already-fixed row never
# matches this pattern again, which is what makes reruns safe.
_TOOL_FAILURE_PATTERN = re.compile(r"^(?P<action>\w+) failed after (?P<attempts>\d+) attempt\(s\): .+$")


def backfill() -> dict:
    session = SessionLocal()
    try:
        closing_rows = session.execute(select(DecisionLog).where(DecisionLog.reason == _OLD_CLOSING_REASON)).scalars().all()
        for row in closing_rows:
            row.reason = _NEW_CLOSING_REASON

        tool_failure_candidates = (
            session.execute(select(DecisionLog).where(DecisionLog.reason.like("%failed after%attempt%"))).scalars().all()
        )
        n_tool_failure_updated = 0
        for row in tool_failure_candidates:
            match = _TOOL_FAILURE_PATTERN.match(row.reason)
            if not match:
                continue
            new_reason = f"{match.group('action')} failed after {match.group('attempts')} attempt(s), fell back to wait"
            if row.reason != new_reason:
                row.reason = new_reason
                n_tool_failure_updated += 1

        session.commit()
        return {"closing_entries_updated": len(closing_rows), "tool_failure_entries_updated": n_tool_failure_updated}
    finally:
        session.close()


if __name__ == "__main__":
    result = backfill()
    print(
        f"Updated {result['closing_entries_updated']} closing-entry reason(s) and "
        f"{result['tool_failure_entries_updated']} tool-failure reason(s) -- 0/0 means this DB already had both fixes."
    )
