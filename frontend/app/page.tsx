import Link from "next/link";
import { Compass, FileSearch, Gauge, ShieldCheck, TableProperties } from "lucide-react";
import type { CSSProperties, ReactNode } from "react";
import { getAttribution, getMetrics } from "@/lib/api";
import { formatCurrency, formatPercent } from "@/lib/ui";
import ChannelLiftChart, { ChannelLift } from "./ChannelLiftChart";
import FadeIn from "./FadeIn";
import HeroActions from "./HeroActions";
import HeroBackground from "./HeroBackground";
import KeyDecisions from "./KeyDecisions";
import PipelineViz from "./PipelineViz";
import { ConfidenceMeterVisual, NoiseVsSignalVisual, WastedSpendVisual } from "./ProblemVisual";

// Landing page (Phase C redesign, "Arbiter" identity). Every number on this
// page is fetched live from the real backend; nothing here is hardcoded
// marketing copy pretending to be a metric. If the backend is unreachable,
// the proof-metrics section degrades gracefully rather than breaking the
// whole page (this is a landing page, not a critical data screen).
//
// Framing note (2026-09-04): the per-channel lift chart below is shown
// instead of a single flat pooled number because channel-level composition
// legitimately varies -- it's a transparency choice, not a workaround for a
// bad headline. Don't hardcode a specific channel's sign/direction in this
// file's copy again: it changes with the dataset instance (see CLAUDE.md's
// "CURRENT CANONICAL STATE" section for whatever is true right now) and a
// hardcoded claim here has already gone stale once.

const PROBLEMS = [
  {
    n: "01",
    t: "Chasing everything wastes money",
    d: "A flat \"email everyone\" policy spends cost and friction on invoices that were always going to pay on their own, or were never going to pay at all.",
    visual: <WastedSpendVisual />,
  },
  {
    n: "02",
    t: "No confidence signal on promises",
    d: "\"I'll pay Friday\" — is that credible? Without a calibrated model, every promise looks identical.",
    visual: <ConfidenceMeterVisual />,
  },
  {
    n: "03",
    t: "No way to prove it worked",
    d: "Recovery went up — but would it have gone up anyway? Without a control group you're measuring noise.",
    visual: <NoiseVsSignalVisual />,
  },
];

const WALKTHROUGH = [
  { icon: FileSearch, label: "Root cause" },
  { icon: Gauge, label: "Recoverability" },
  { icon: TableProperties, label: "Economics" },
  { icon: ShieldCheck, label: "Policy" },
  { icon: Compass, label: "Timeline" },
];

interface ProofMetrics {
  netImprovement: number;
  recoveryRate: number;
  nInvoices: number;
  positiveChannels: number;
  totalChannels: number;
  channelLifts: ChannelLift[];
}

export default async function LandingPage() {
  let proofMetrics: ProofMetrics | null = null;
  try {
    const [metrics, attribution] = await Promise.all([getMetrics(), getAttribution()]);
    const byAction = attribution.slices.filter((s) => s.segment === null && s.action !== null);
    proofMetrics = {
      netImprovement: metrics.engine.net_expected_recovered - metrics.baseline.net_expected_recovered,
      recoveryRate: metrics.engine.recovery_rate,
      nInvoices: metrics.engine.n_invoices,
      positiveChannels: byAction.filter((s) => s.incremental_recovery_rate > 0).length,
      totalChannels: byAction.length,
      channelLifts: byAction.map((s) => ({ action: s.action as string, incrementalRecoveryRate: s.incremental_recovery_rate })),
    };
  } catch {
    proofMetrics = null;
  }

  return (
    <div className="space-y-28 pb-16">
      {/* ================= Hero ================= */}
      <section className="relative flex flex-col items-start gap-8 pt-6 sm:pt-14">
        <HeroBackground />

        <FadeIn>
          <span className="label inline-flex items-center gap-2 rounded-sm border border-border bg-surface/70 px-2.5 py-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-status-success" />
            Engine live &nbsp;·&nbsp; Deterministic policy gate &nbsp;·&nbsp; Real-time recovery decisions
          </span>
        </FadeIn>

        <FadeIn delay={0.05}>
          <h1 className="max-w-2xl text-5xl font-semibold leading-[1.05] tracking-tight sm:text-6xl">
            <span className="block text-text">Chase it.</span>
            <span className="block text-text-muted">Or don&rsquo;t.</span>
            <span className="block text-accent-text">Arbiter knows which.</span>
          </h1>
        </FadeIn>

        <FadeIn delay={0.12}>
          <p className="max-w-xl text-base text-text-muted sm:text-lg">
            For every overdue B2B invoice, Arbiter decides <em>whether</em> chasing it is worth it,{" "}
            <em>why</em> it&rsquo;s late, <em>how confident</em> to be in a payment promise, and{" "}
            <em>which</em> intervention is cheapest-and-effective — then executes it inside compliant
            guardrails and <em>proves</em> how much money it actually caused to come in, via a randomized
            holdout, not a guess.
          </p>
        </FadeIn>

        <HeroActions />

        {/* Two headline numbers only, as interactive stat blocks -- the full
            4-stat + chart breakdown lives once, further down in "Proof, not
            a pitch". Showing the same numbers twice (once as plain text
            here, once boxed there) was the actual complaint -- fixed by not
            duplicating, not just by restyling. */}
        {proofMetrics && (
          <FadeIn delay={0.2} className="grid w-full max-w-md grid-cols-2 gap-4">
            <StatBlock label="Net EV improvement" value={formatCurrency(proofMetrics.netImprovement)} />
            <StatBlock label="Engine recovery rate" value={formatPercent(proofMetrics.recoveryRate)} />
          </FadeIn>
        )}
      </section>

      {/* ================= Problem — three equal cards, each its own visual =================
          Was a 2-col "lead" card + 2 stacked smaller ones -- the lead card
          ended up much taller than its content needed, reading as mostly
          empty space. Equal-sized cards fixed that structurally rather
          than needing to fill the extra height with more decoration. */}
      <FadeIn>
        <section className="relative">
          <div aria-hidden className="section-glow" style={{ "--glow-x": "10%" } as CSSProperties} />
          <h2 className="section-heading mb-6">The problem</h2>
          <div className="grid gap-4 sm:grid-cols-3">
            {PROBLEMS.map((p) => (
              <ProblemCard key={p.n} {...p} />
            ))}
          </div>
        </section>
      </FadeIn>

      {/* ================= Pipeline ================= */}
      <FadeIn>
        <section>
          <h2 className="section-heading mb-3">How it works</h2>
          <p className="mb-4 max-w-2xl text-text-muted">
            One event, one graph invocation, seven stages — orchestrated by LangGraph. Scroll to see the flow.
          </p>
          <PipelineViz />
        </section>
      </FadeIn>

      {/* ================= Proof metrics ================= */}
      <FadeIn>
        <section>
          <h2 className="section-heading mb-3">Proof, not a pitch</h2>
          <p className="mb-6 max-w-2xl text-text-muted">
            Fetched live from this deployment&rsquo;s own persisted decisions and attribution experiment —
            not illustrative copy.
          </p>
          {proofMetrics ? (
            <div className="grid gap-4 lg:grid-cols-5">
              <div className="grid-lines relative h-full overflow-hidden rounded-panel border border-border lg:col-span-3">
                <div className="grid h-full grid-cols-2 divide-x divide-y divide-border">
                  <ProofTile label="Live invoices scored" value={String(proofMetrics.nInvoices)} />
                  <ProofTile label="Engine recovery rate" value={formatPercent(proofMetrics.recoveryRate)} />
                  <ProofTile label="Net EV improvement" value={formatCurrency(proofMetrics.netImprovement)} accent />
                  <ProofTile
                    label="Channels with positive lift"
                    value={`${proofMetrics.positiveChannels} / ${proofMetrics.totalChannels}`}
                    accent
                  />
                </div>
              </div>
              <div className="flex h-full flex-col rounded-panel border border-border bg-surface/60 p-5 lg:col-span-2">
                <div className="label mb-2 text-text-faint">Measured lift — positive channels</div>
                <div className="flex flex-1 items-center">
                  <ChannelLiftChart data={proofMetrics.channelLifts} />
                </div>
              </div>
            </div>
          ) : (
            <p className="rounded-card border border-dashed border-border-strong p-6 text-sm text-text-faint">
              Live metrics are temporarily unavailable — visit{" "}
              <Link href="/metrics" className="text-accent-text hover:underline">
                the metrics screen
              </Link>{" "}
              directly once the backend responds.
            </p>
          )}
          <p className="mt-3 text-xs text-text-faint">
            Full per-channel and per-segment breakdown on the{" "}
            <Link href="/metrics" className="text-accent-text hover:underline">
              metrics page
            </Link>
            .
          </p>
        </section>
      </FadeIn>

      {/* ================= Key decisions — icon grid, its own design language ================= */}
      <FadeIn>
        <section className="relative">
          <div aria-hidden className="section-glow" style={{ "--glow-x": "85%" } as CSSProperties} />
          <h2 className="section-heading mb-3">Key design decisions</h2>
          <p className="mb-6 max-w-2xl text-text-muted">
            The choices that mattered more than the model architecture.
          </p>
          <KeyDecisions />
        </section>
      </FadeIn>

      {/* ================= CTA ================= */}
      <FadeIn>
        <section className="grid-lines relative overflow-hidden rounded-panel border border-accent/25 bg-accent-soft/40 p-8 sm:p-14">
          <div className="mx-auto max-w-2xl text-center">
            <h2 className="text-2xl font-semibold text-text sm:text-3xl">See it decide, in real time.</h2>
            <p className="mx-auto mt-2 max-w-xl text-sm text-text-muted">
              Open the console, pick a curated example, and walk the full trace end to end.
            </p>
          </div>

          <div className="mx-auto mt-8 flex max-w-3xl flex-wrap items-center justify-center gap-3">
            {WALKTHROUGH.map((step, i) => (
              <div key={step.label} className="flex items-center gap-3">
                <div className="flex items-center gap-2 rounded-lg border border-border bg-surface/70 px-3.5 py-2">
                  <step.icon size={14} className="text-accent-text" />
                  <span className="text-xs font-medium text-text-muted">{step.label}</span>
                </div>
                {i < WALKTHROUGH.length - 1 && <span className="text-text-faint">→</span>}
              </div>
            ))}
          </div>

          <div className="mt-8 flex justify-center">
            <Link
              href="/invoices"
              className="rounded-lg bg-accent px-6 py-3 text-sm font-semibold text-white shadow-accent transition-transform active:scale-[0.98]"
            >
              Open Console →
            </Link>
          </div>
        </section>
      </FadeIn>
    </div>
  );
}

function StatBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="spotlight rounded-card border border-border bg-surface/70 p-4 transition-colors hover:border-accent/40">
      <div className="label">{label}</div>
      <div className="mt-1.5 font-mono-tabular text-xl font-semibold text-accent-text sm:text-2xl">{value}</div>
    </div>
  );
}

function ProblemCard({
  n,
  t,
  d,
  visual,
}: {
  n: string;
  t: string;
  d: string;
  visual: ReactNode;
}) {
  return (
    <div className="spotlight flex flex-col rounded-card border border-border bg-surface/60 p-5 sm:p-6">
      <div className="flex items-center justify-between">
        <span className="label text-text-faint">{n}</span>
      </div>
      <div className="flex flex-1 items-center justify-center">{visual}</div>
      <div>
        <div className="font-display text-base font-semibold text-text">{t}</div>
        <p className="mt-2 text-sm text-text-faint">{d}</p>
      </div>
    </div>
  );
}

function ProofTile({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="flex flex-col justify-center p-5 sm:p-6">
      <div className="label">{label}</div>
      <div className={`mt-2 font-mono-tabular text-2xl font-semibold sm:text-3xl ${accent ? "text-accent-text" : "text-text"}`}>
        {value}
      </div>
    </div>
  );
}
