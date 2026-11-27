"use client";

// Tabs for the Insights area.
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/insights", label: "Dashboard" },
  { href: "/insights/pipeline", label: "Interview pipeline" },
  { href: "/insights/timeline", label: "Outcome timeline" },
  { href: "/insights/companies", label: "Companies" },
  { href: "/insights/resumes", label: "Resume performance" },
  { href: "/insights/boards", label: "Job boards" },
  { href: "/insights/recommendations", label: "Recommendations" },
];

export function InsightsNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Insights" className="flex flex-wrap gap-1">
      {TABS.map((t) => {
        const active = t.href === "/insights" ? pathname === "/insights" || pathname === "/" : pathname.startsWith(t.href);
        return (
          <Link
            key={t.href}
            href={t.href}
            aria-current={active ? "page" : undefined}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              active
                ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            }`}
          >
            {t.label}
          </Link>
        );
      })}
    </nav>
  );
}

export function DataNote() {
  return (
    <p className="text-sm text-zinc-600 dark:text-zinc-400">
      Everything here comes from your own applications and the outcomes you record. Rates show 95% intervals;
      differences are only called out when they hold up statistically.
    </p>
  );
}
