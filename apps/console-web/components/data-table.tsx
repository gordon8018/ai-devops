import Link from "next/link";
import { ReactNode } from "react";

type Column = {
  key: string;
  label: string;
  render?: (row: Record<string, unknown>) => ReactNode;
};

export function DataTable({
  columns,
  rows,
  emptyText,
}: {
  columns: Column[];
  rows: Record<string, unknown>[];
  emptyText: string;
}) {
  if (rows.length === 0) {
    return <p className="empty-state">{emptyText}</p>;
  }

  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.key}>{column.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={String(row.id ?? row.workItemId ?? row.releaseId ?? row.incidentId ?? index)}>
              {columns.map((column) => (
                <td key={column.key}>
                  {column.render ? column.render(row) : String(row[column.key] ?? "-")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function WorkspaceLink({ workItemId }: { workItemId: string }) {
  return (
    <Link href={`/work-items/${workItemId}`} className="inline-link">
      {workItemId}
    </Link>
  );
}
