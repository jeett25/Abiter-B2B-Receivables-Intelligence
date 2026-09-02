"use client";

import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

// ssr:false is only legal inside a Client Component in the App Router --
// this wrapper exists specifically so Hero3D (a real WebGL canvas) never
// attempts to render on the server.
const Hero3D = dynamic(() => import("./Hero3D"), { ssr: false });

function prefersReducedMotion() {
  if (typeof window === "undefined") return false;
  return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

export default function HeroBackground() {
  // Lazy initializer reads the real value on first client render instead of
  // defaulting to false and correcting it via a setState-in-effect (flagged
  // by the react-hooks lint rule -- that pattern causes an extra render).
  // The effect below only SUBSCRIBES to later changes, it never sets state
  // synchronously on mount.
  const [reducedMotion, setReducedMotion] = useState(prefersReducedMotion);

  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const listener = (e: MediaQueryListEvent) => setReducedMotion(e.matches);
    mq.addEventListener("change", listener);
    return () => mq.removeEventListener("change", listener);
  }, []);

  return (
    // Full-bleed breakout: its positioned ancestor is the hero <section>,
    // which lives inside <main className="max-w-7xl mx-auto...">, so a
    // plain `inset-x-0` only spans that ~1280px content column -- on any
    // screen wider than that, the true viewport margins outside it showed
    // flat body background with none of the glow/grid/constellation
    // reaching them, reading as a harsh black frame around the hero. The
    // left-1/2 + negative-50vw-margin + w-screen recipe below re-centers
    // this element across the REAL viewport width regardless of how narrow
    // its positioned ancestor is.
    <div
      aria-hidden
      className="pointer-events-none absolute top-0 left-1/2 -z-10 h-[640px] w-screen overflow-hidden sm:h-[720px]"
      style={{ marginLeft: "-50vw" }}
    >
      <div className="absolute inset-0 grid-lines opacity-60 [mask-image:radial-gradient(ellipse_70%_60%_at_50%_0%,black,transparent)]" />
      <div className="blob blob-a" />
      <div className="blob blob-b" />
      <div className="blob blob-c" />
      <Hero3D reducedMotion={reducedMotion} />
      {/* Longer, gentler fade than a plain 2-stop gradient -- the abrupt
          version made the hero's atmosphere feel like it hit a wall rather
          than continuing into the sitewide .ambient-wash below it. */}
      <div className="absolute inset-0 bg-gradient-to-b from-transparent from-30% via-bg/70 via-80% to-bg" />
    </div>
  );
}
