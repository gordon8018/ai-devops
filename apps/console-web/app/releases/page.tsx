import { DataTable, WorkspaceLink } from "../../components/data-table";
import { ErrorBanner } from "../../components/error-banner";
import { Panel } from "../../components/panel";
import { RefreshButton } from "../../components/refresh-button";
import { getReleaseConsole } from "../../lib/console-api";
import { resourceErrorMessage } from "../../lib/console-data.mjs";

export const dynamic = "force-dynamic";

export default async function ReleasesPage() {
  const fetched = await getReleaseConsole();
  const data = fetched ?? { total: 0, byStatus: {}, items: [] };
  const items = Array.isArray(data.items) ? data.items : [];
  const errorMessage = resourceErrorMessage(fetched, "Release Console");

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Release</span>
        <h1>Release Console</h1>
        <p>查看 rollout 进度、当前 stage，以及被回滚的发布记录。</p>
        <RefreshButton />
      </header>

      <ErrorBanner message={errorMessage} />

      <Panel title="Release Summary" eyebrow="Overview">
        <div className="pill-row">
          <span className="pill">Total: {String(data.total ?? 0)}</span>
          {Object.entries((data.byStatus as Record<string, number>) ?? {}).map(([status, count]) => (
            <span className="pill" key={status}>
              {status}: {count}
            </span>
          ))}
        </div>
      </Panel>

      <Panel title="Release Items" eyebrow="Rollout">
        <DataTable
          rows={items as Record<string, unknown>[]}
          emptyText="当前没有 release 数据。"
          columns={[
            { key: "releaseId", label: "Release" },
            {
              key: "workItemId",
              label: "Work Item",
              render: (row) => <WorkspaceLink workItemId={String(row.workItemId ?? "")} />,
            },
            { key: "status", label: "Status" },
            { key: "stage", label: "Stage" },
          ]}
        />
      </Panel>
    </div>
  );
}
