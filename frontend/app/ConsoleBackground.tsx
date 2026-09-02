"use client";

import { useEffect, useRef } from "react";

// Console pages are data-dense, so this stays much more restrained than the
// landing page's hero -- no 3D canvas, just a faint grid texture plus a
// soft glow that follows the cursor (real interactivity, not a looping
// decorative animation) so the page doesn't feel like a "plain table on
// flat black" the way an unstyled admin panel does.
export default function ConsoleBackground() {
  const glowRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleMove(e: MouseEvent) {
      if (!glowRef.current) return;
      glowRef.current.style.setProperty("--mx", `${e.clientX}px`);
      glowRef.current.style.setProperty("--my", `${e.clientY}px`);
    }
    window.addEventListener("mousemove", handleMove);
    return () => window.removeEventListener("mousemove", handleMove);
  }, []);

  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <div className="absolute inset-0 grid-lines opacity-[0.35] [mask-image:radial-gradient(ellipse_80%_60%_at_50%_0%,black,transparent)]" />
      <div
        ref={glowRef}
        className="absolute inset-0 opacity-70 transition-opacity duration-300"
        style={{
          background: "radial-gradient(480px circle at var(--mx, 50%) var(--my, 20%), rgb(61 116 240 / 0.06), transparent 70%)",
        }}
      />
    </div>
  );
}
