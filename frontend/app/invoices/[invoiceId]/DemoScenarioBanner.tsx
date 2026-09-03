import { Sparkles } from "lucide-react";
import type { CSSProperties } from "react";
import { DemoFixture } from "@/lib/types";

// Added 2026-09-03 to close a real gap: the "Example scenarios" menu label
// (e.g. "Tool/LLM failure (forced, rehearsed)") gives context BEFORE a
// click, but nothing on the Invoice Detail page itself explains what's
// being shown once you're actually there -- a viewer with no source-code
// context (a recruiter, not someone who's read CLAUDE.md) has no way to
// tell a deliberately-staged demonstration apart from a real bug or an
// arbitrary invoice. Renders only when the invoice being viewed is one of
// the 6 curated fixtures; silent (returns null) for the other ~385.
export default function DemoScenarioBanner({ fixture }: { fixture: DemoFixture | undefined }) {
  if (!fixture) return null;

  return (
    <div className="relative overflow-hidden rounded-card border border-accent/30 bg-accent-soft/40 p-4 sm:p-5">
      <div aria-hidden className="section-glow" style={{ "--glow-x": "85%" } as CSSProperties} />
      <div className="relative flex items-start gap-3">
        <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-white">
          <Sparkles size={16} />
        </span>
        <div>
          <div className="label !text-accent-text">Curated demo scenario &middot; {fixture.label}</div>
          <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-text">{fixture.explanation}</p>
        </div>
      </div>
    </div>
  );
}
