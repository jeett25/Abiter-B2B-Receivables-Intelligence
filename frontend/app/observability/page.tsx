import { CheckCircle2, Layers, ListChecks, Target } from "lucide-react";
import { Card, IconStat, PageHeader } from "@/lib/ui";

// Subtask 14 (Phase D): "small, mostly static reported numbers" per the
// build plan -- deliberately NOT a new live-eval endpoint or a monitoring
// stack. Every figure below is a real, already-documented result from the
// project's own Day 2-4 build process (see backend/app/ml/DECISIONS.md,
// app/retrieval/hybrid_search.py's relevance diagnostic, and
// app/agent/DECISIONS.md) -- this page presents them, it doesn't recompute
// them. That's also why this is a plain Server Component with no fetch: the
// numbers don't change between page loads the way /metrics's live-persisted
// data does.

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-xs text-text-faint">{label}</div>
      <div className="font-mono-tabular font-medium text-text">{value}</div>
    </div>
  );
}

function SafetyCheckRow({ label }: { label: string }) {
  return (
    <li className="flex items-center gap-2.5 text-sm text-text">
      <CheckCircle2 size={15} className="shrink-0 text-status-success" />
      {label}
    </li>
  );
}

export default function ObservabilityPage() {
  return (
    <div className="space-y-10">
      <PageHeader
        title="Observability"
        subtitle="One-time, documented evaluation results from the system's own build process (Days 2–4) — precomputed and reported here, not recomputed on every page load the way the live Metrics page is."
      />

      <section className="space-y-4">
        <h2 className="section-heading">Model calibration</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="p-5 sm:p-6">
            <div className="label mb-4 !text-text-muted">Recovery probability model</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              <StatRow label="ROC-AUC — Experiment A (time-based)" value="≈0.829" />
              <StatRow label="ROC-AUC — Experiment B (unseen customer)" value="≈0.803" />
              <StatRow label="PR-AUC" value="≈0.92" />
              <StatRow label="Brier score" value="≈0.116–0.117" />
            </div>
            <p className="mt-4 text-xs text-text-faint">
              Experiment A trains on months 1–9 and tests on 10–11 — the production-relevant split, and the one this
              model is actually calibrated against. Experiment B holds out entire customers instead, deliberately
              uncalibrated — its lower score is the expected, correct signature of a harder task (generalizing to a
              customer never seen in training), not a regression.
            </p>
          </Card>
          <Card className="p-5 sm:p-6">
            <div className="label mb-4 !text-text-muted">Promise-to-pay (PTP) model</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              <StatRow label="ROC-AUC — Experiment A" value="≈0.835" />
              <StatRow label="ROC-AUC — Experiment B" value="≈0.808" />
              <StatRow label="PR-AUC" value="≈0.89" />
              <StatRow label="Broken-promise F1 @ 0.5" value="0.643" />
            </div>
            <p className="mt-4 text-xs text-text-faint">
              Broken-promise detection at the default 0.5 threshold: precision 0.767, recall 0.554. The model
              under-weights promise history for one archetype (frequent promise-breakers) — a known, investigated
              limitation logged in the ML decisions record rather than silently smoothed over.
            </p>
          </Card>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="section-heading">Retrieval quality</h2>
        <Card className="p-5 sm:p-6">
          <div className="label mb-1 !text-text-muted">Hybrid retrieval — BM25 + pgvector + amount proximity, fused via Reciprocal Rank Fusion</div>
          <p className="mb-4 text-xs text-text-faint">
            Verified two ways: a strict self-retrieval test (does a historical case retrieve itself at rank 1 when
            queried against its own text?), and an archetype-cohesion diagnostic — hidden-ground-truth,
            verification-only — checking whether retrieval actually surfaces similar-outcome cases more often than
            chance.
          </p>
          <div className="grid grid-cols-2 gap-4">
            <IconStat icon={Target} label="Self-retrieval @ rank 1" value="Pass" tone="success" sub="every historical case retrieves itself first" />
            <IconStat icon={Layers} label="Archetype cohesion" value="2.00x" tone="accent" sub="vs. a random-baseline retrieval" />
          </div>
        </Card>
      </section>

      <section className="space-y-4">
        <h2 className="section-heading">Agent &amp; LLM reliability</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <Card className="p-5 sm:p-6">
            <div className="label mb-4 !text-text-muted">Promise-extraction LLM</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              <StatRow label="Model" value="Groq — gpt-oss-120b" />
              <StatRow label="Mode" value="JSON mode, temp 0" />
              <StatRow label="Retry policy" value="2 attempts" />
              <StatRow label="Fallback on failure" value="null" />
            </div>
            <p className="mt-4 text-xs text-text-faint">
              The LLM only extracts a promise from customer text — it never decides whether to believe it. That
              credibility judgment stays with the calibrated PTP model above. On two failed or malformed extraction
              attempts, the fallback is always <span className="text-text-muted">null</span>, never a fabricated
              promise.
            </p>
          </Card>
          <Card className="p-5 sm:p-6">
            <div className="label mb-4 !text-text-muted">Final integration pass — safety checks</div>
            <ul className="space-y-2">
              <SafetyCheckRow label="No duplicate event processing" />
              <SafetyCheckRow label="No policy-gate bypass" />
              <SafetyCheckRow label="No business-hours violations" />
              <SafetyCheckRow label="Every result has a real, non-placeholder score" />
              <SafetyCheckRow label="No hidden-ground-truth identifiers leaked" />
            </ul>
            <p className="mt-3 text-xs text-text-faint">
              Run across the full 900-invoice live pool. That pass processed only INVOICE_OVERDUE events, so it
              invoked zero LLM calls by construction — promise extraction is exercised separately, in the demo
              scenarios and the reassessment-loop tests.
            </p>
          </Card>
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <IconStat icon={ListChecks} label="Automated tests" value="222" tone="neutral" sub="passing, project-wide" />
          <IconStat icon={CheckCircle2} label="Safety checks" value="7 / 7" tone="success" sub="final integration pass" />
          <IconStat icon={Target} label="Live pool scored" value="900 / 900" tone="accent" sub="no placeholder scores" />
        </div>
      </section>
    </div>
  );
}
