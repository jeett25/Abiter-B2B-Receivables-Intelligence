"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/lib/ui";

const LINKS = [
  { href: "/invoices", label: "Invoices" },
  { href: "/metrics", label: "Metrics" },
];

// Plain text nav, no pill/background treatment (2026-09-02) -- the header
// itself has no bar behind it now, so a bordered/filled link would be the
// only visibly "boxed" thing floating on the page, inconsistent with
// everything else. Active/hover state is color + underline only.
export default function NavLinks() {
  const pathname = usePathname();
  return (
    <div className="flex items-center gap-6">
      {LINKS.map((link) => {
        const active = pathname?.startsWith(link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            className={cx(
              "text-sm font-medium underline-offset-4 transition-colors",
              active ? "text-text underline decoration-accent" : "text-text-muted hover:text-text"
            )}
          >
            {link.label}
          </Link>
        );
      })}
    </div>
  );
}
