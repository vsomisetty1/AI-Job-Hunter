// Download links for a generated document (PDF and DOCX).
import { packagesApi } from "@/lib/api/packages";
import type { PackageDoc } from "@/types";

export function Downloads({ id, doc, label }: { id: string; doc: PackageDoc; label: string }) {
  return (
    <span className="flex flex-wrap gap-3 text-sm">
      {(["pdf", "docx"] as const).map((f) => (
        <a
          key={f}
          href={packagesApi.fileUrl(id, doc, f)}
          className="text-indigo-600 hover:underline dark:text-indigo-400"
          download
        >
          {label} ({f.toUpperCase()})
        </a>
      ))}
    </span>
  );
}
