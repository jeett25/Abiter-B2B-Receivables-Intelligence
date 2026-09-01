"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { cx } from "@/lib/ui";

const LINKS = [
  { href: "/invoices", label: "Invoices" },
  { href: "/metrics", label: "Metrics" },
];

export default function NavLinks() {
  const pathname = usePathname();
  return (
    <div className="flex items-center gap-1">
      {LINKS.map((link) => {
        const active = pathname?.startsWith(link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            className={cx(
              "rounded-lg px-3 py-1.5 text-sm font-medium transition-colors",
              active ? "bg-accent-soft text-accent-text" : "text-text-muted hover:text-text hover:bg-surface-2"
            )}
          >
            {link.label}
          </Link>
        );
      })}
    </div>
  );
}
