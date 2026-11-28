"use client";

// Section tabs for the Applications area.
import Link from "next/link";
import { usePathname } from "next/navigation";

const TABS = [
  { href: "/applications", label: "Queue" },
  { href: "/applications/history", label: "Submission history" },
  { href: "/applications/logs", label: "Automation logs" },
];

export function ApplicationsNav() {
  const pathname = usePathname();
  return (
    <nav aria-label="Applications" className="flex flex-wrap gap-1">
      {TABS.map((t) => {
        const active = t.href === "/applications" ? pathname === t.href : pathname.startsWith(t.href);
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

export function ApprovalModeNote() {
  return (
    <p className="text-sm text-zinc-600 dark:text-zinc-400">
      Approval mode: the app opens the job&apos;s application form, uploads your tailored resume and cover
      letter and fills in answers, then stops. Nothing is sent until you review the form and press Submit.
    </p>
  );
}
