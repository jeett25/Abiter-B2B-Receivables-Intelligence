import Link from "next/link";
import { getMetrics } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/ui";
import FadeIn from "./FadeIn";
import HeroActions from "./HeroActions";
import PipelineViz from "./PipelineViz";

// Landing page (subtask 13) -- built after the console works, so it isn't
// designed around functionality that later changed. Every number on this
// page is fetched live from the real backend; nothing here is hardcoded
// marketing copy pretending to be a metric. If the backend is unreachable,
// the proof-metrics section degrades gracefully rather than breaking the
// whole page (this is a landing page, not a critical data screen).

const KEY_DECISIONS = [
  {
    title: "No LLM chooses the action",
    body: "The Economics Engine and deterministic Policy/Safety Gate make every decision. The only LLM call in the system extracts a payment promise from a customer's message — it never influences recovery scoring, economics, or policy.",
  },
  {
    title: "Attribution over vanity metrics",
    body: "A randomized holdout (treatment vs. control) measures real incremental recovery, not just 'we sent more messages.' Day 5's experiment closes the loop by correcting the Economics Engine's own uplift assumptions against what was actually observed.",
  },
  {
    title: "Policy gate is a hard boundary",
    body: "8 fixed-priority rules — already-paid (cross-referenced against the real payments ledger, not invoice status), disputed invoices, contact caps, cooldowns, business hours, human-approval routing for large escalations — sit between the model's recommendation and any real-world action.",
  },
  {
    title: "Every score is point-in-time safe",
    body: "Recovery and promise-to-pay models are trained and scored strictly as of a cutoff — no feature is ever computed using information that wouldn't have existed yet. Verified with adversarial future-leakage regression tests, not just asserted.",
  },
];

export default async function LandingPage() {
  let proofMetrics: { netImprovement: number; recoveryRate: number; incrementalRecovery: number | null; nInvoices: number } | null = null;
  try {
    const metrics = await getMetrics();
    proofMetrics = {
      netImprovement: metrics.engine.net_expected_recovered - metrics.baseline.net_expected_recovered,
      recoveryRate: metrics.engine.recovery_rate,
      incrementalRecovery: metrics.attribution?.incremental_recovery_rate ?? null,
      nInvoices: metrics.engine.n_invoices,
    };
  } catch {
    proofMetrics = null;
  }

  return (
    <div className="space-y-24 pb-16">
      {/* Hero */}
      <section className="relative flex flex-col items-start gap-6 pt-8 sm:pt-16">
        <FadeIn>
          <span className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-text-muted">
            <span className="h-1.5 w-1.5 rounded-full bg-status-success" />
            Razorpay AI Buildathon 2026 · Track 03, AI Revenue Recovery
          </span>
        </FadeIn>
        <FadeIn delay={0.05}>
          <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-text sm:text-5xl">
            A decision engine for overdue B2B invoices — not a collections bot.
          </h1>
        </FadeIn>
        <FadeIn delay={0.1}>
          <p className="max-w-2xl text-base text-text-muted sm:text-lg">
            For every overdue invoice, it decides <em>whether</em> chasing it is worth it, <em>why</em> it&rsquo;s
            late, <em>how confident</em> to be in a payment promise, <em>which</em> intervention is
            cheapest-and-effective, executes it inside compliant guardrails, and <em>proves</em> how much money it
            actually caused to come in — via a randomized holdout, not a guess.
          </p>
        </FadeIn>
        <HeroActions />
      </section>

      {/* Problem */}
      <FadeIn>
        <section className="grid gap-6 sm:grid-cols-3">
          {[
            { n: "01", t: "Chasing everything wastes money", d: "A flat 'email everyone' policy spends cost + friction on invoices that were always going to pay, or never will." },
            { n: "02", t: "No confidence signal on promises", d: "A customer says 'I'll pay Friday' — is that credible? Without a calibrated model, every promise looks the same." },
            { n: "03", t: "No way to prove it worked", d: "Recovery rate went up — but would it have gone up anyway? Without a control group, you're measuring noise." },
          ].map((p) => (
            <div key={p.n} className="rounded-2xl border border-border bg-surface/60 p-5">
              <div className="font-mono-tabular text-xs text-text-faint">{p.n}</div>
              <div className="mt-2 text-sm font-semibold text-text">{p.t}</div>
              <p className="mt-1.5 text-sm text-text-faint">{p.d}</p>
            </div>
          ))}
        </section>
      </FadeIn>

      {/* Pipeline */}
      <FadeIn>
        <section>
          <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-accent-text">How it works</h2>
          <p className="mb-6 max-w-2xl text-text-muted">
            One event, one graph invocation, seven stages — orchestrated by LangGraph, with a feedback loop back
            into the economics that drive the next decision.
          </p>
          <PipelineViz />
        </section>
      </FadeIn>

      {/* Proof metrics */}
      <FadeIn>
        <section>
          <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-accent-text">Proof, not a pitch</h2>
          <p className="mb-6 max-w-2xl text-text-muted">
            Numbers below are fetched live from this deployment&rsquo;s own persisted decisions and attribution
            experiment — not illustrative copy.
          </p>
          {proofMetrics ? (
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <ProofTile label="Live invoices scored" value={String(proofMetrics.nInvoices)} />
              <ProofTile label="Engine recovery rate" value={formatPercent(proofMetrics.recoveryRate)} />
              <ProofTile label="Net EV improvement vs. baseline" value={formatCurrency(proofMetrics.netImprovement)} accent />
              <ProofTile
                label="Measured incremental recovery"
                value={proofMetrics.incrementalRecovery !== null ? formatPercent(proofMetrics.incrementalRecovery) : "pending"}
                accent
              />
            </div>
          ) : (
            <p className="rounded-xl border border-dashed border-border-strong p-6 text-sm text-text-faint">
              Live metrics are temporarily unavailable — visit <Link href="/metrics" className="text-accent-text hover:underline">the metrics screen</Link> directly once the backend responds.
            </p>
          )}
        </section>
      </FadeIn>

      {/* Key decisions */}
      <FadeIn>
        <section>
          <h2 className="mb-1 text-sm font-semibold uppercase tracking-wide text-accent-text">Key design decisions</h2>
          <p className="mb-6 max-w-2xl text-text-muted">
            The choices that mattered more than the model architecture.
          </p>
          <div className="grid gap-4 sm:grid-cols-2">
            {KEY_DECISIONS.map((d) => (
              <div key={d.title} className="rounded-2xl border border-border bg-surface/60 p-5">
                <div className="text-sm font-semibold text-text">{d.title}</div>
                <p className="mt-1.5 text-sm leading-relaxed text-text-faint">{d.body}</p>
              </div>
            ))}
          </div>
        </section>
      </FadeIn>

      {/* CTA */}
      <FadeIn>
        <section className="rounded-3xl border border-accent/25 bg-accent-soft/40 p-8 text-center sm:p-12">
          <h2 className="text-2xl font-semibold text-text">See it decide, in real time.</h2>
          <p className="mx-auto mt-2 max-w-xl text-sm text-text-muted">
            Open the console, pick a curated demo invoice, and walk the full trace — root cause, recoverability
            score, candidate-action economics, retrieved cases, policy check, and the timeline that resulted.
          </p>
          <div className="mt-6 flex justify-center">
            <Link
              href="/invoices"
              className="rounded-xl bg-accent px-6 py-3 text-sm font-semibold text-white shadow-elevated hover:bg-accent-hover transition-colors"
            >
              Open Console →
            </Link>
          </div>
        </section>
      </FadeIn>
    </div>
  );
}

function ProofTile({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-xl border border-border bg-surface-2/60 p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-text-muted">{label}</div>
      <div className={`mt-1.5 text-2xl font-semibold font-mono-tabular ${accent ? "text-accent-text" : "text-text"}`}>
        {value}
      </div>
    </div>
  );
}
