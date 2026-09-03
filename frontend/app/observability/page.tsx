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
      <PageHeader title="Observability" subtitle="Evaluation results from the system's own build and test process." />

      <section className="space-y-4">
        <h2 className="section-heading">Model calibration</h2>
        <div className="grid gap-4 md:grid-cols-3">
          <Card className="p-5 sm:p-6">
            <div className="label mb-4 !text-text-muted">Recovery probability model</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              <StatRow label="ROC-AUC — Experiment A (time-based)" value="≈0.829" />
              <StatRow label="ROC-AUC — Experiment B (unseen customer)" value="≈0.803" />
              <StatRow label="PR-AUC" value="≈0.92" />
              <StatRow label="Brier score" value="≈0.116–0.117" />
            </div>
            <p className="mt-4 text-xs text-text-faint">
              Experiment A (time-based) is the calibrated, production-relevant split. Experiment B holds out entire
              customers — its lower score reflects a harder task, not a regression.
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
              Broken-promise detection at 0.5 threshold: precision 0.767, recall 0.554. One known limitation (frequent
              promise-breakers) is documented, not hidden.
            </p>
          </Card>
          <Card className="p-5 sm:p-6">
            <div className="label mb-4 !text-text-muted">Root-cause model (cash-flow stress vs. oversight)</div>
            <div className="grid grid-cols-2 gap-x-4 gap-y-3">
              <StatRow label="ROC-AUC — Experiment A" value="≈0.757" />
              <StatRow label="PR-AUC" value="≈0.648" />
              <StatRow label="Brier score (calibrated)" value="≈0.196" />
              <StatRow label="Training population" value="Non-disputed only" />
            </div>
            <p className="mt-4 text-xs text-text-faint">
              2-class only: disputes are handled deterministically by the Policy Gate, so this model separates
              cash-flow stress from oversight for non-disputed invoices only.
            </p>
          </Card>
        </div>
      </section>

      <section className="space-y-4">
        <h2 className="section-heading">Retrieval quality</h2>
        <Card className="p-5 sm:p-6">
          <div className="label mb-1 !text-text-muted">Hybrid retrieval — BM25 + pgvector + amount proximity, fused via Reciprocal Rank Fusion</div>
          <p className="mb-4 text-xs text-text-faint">
            Verified via self-retrieval (does a case retrieve itself at rank 1?) and archetype cohesion (similar
            cases surfaced more than chance).
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
              Extracts promises only — never judges credibility (that&rsquo;s the PTP model&rsquo;s job). Fails safe
              to <span className="text-text-muted">null</span>, never fabricates one.
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
            <p className="mt-3 text-xs text-text-faint">Run across the full 900-invoice live pool.</p>
          </Card>
        </div>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          <IconStat icon={ListChecks} label="Automated tests" value="312 / 315" tone="neutral" sub="passing, project-wide" />
          <IconStat icon={CheckCircle2} label="Safety checks" value="7 / 7" tone="success" sub="final integration pass" />
          <IconStat icon={Target} label="Live pool scored" value="900 / 900" tone="accent" sub="no placeholder scores" />
        </div>
      </section>
    </div>
  );
}
