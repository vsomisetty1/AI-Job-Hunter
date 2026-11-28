// A plain table driven by column definitions; cells render as text unless a
// column renders them itself (never as HTML).
import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  cell: (row: T) => ReactNode;
  className?: string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  empty = "Nothing to show.",
  caption,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  empty?: ReactNode;
  caption?: string;
}) {
  if (rows.length === 0) return <p className="text-sm text-zinc-500">{empty}</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead className="text-xs uppercase text-zinc-500">
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" className={`py-2 pr-4 ${c.className ?? ""}`}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800">
          {rows.map((row) => (
            <tr key={rowKey(row)} className="align-top">
              {columns.map((c) => (
                <td key={c.key} className={`py-2 pr-4 ${c.className ?? ""}`}>
                  {c.cell(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
