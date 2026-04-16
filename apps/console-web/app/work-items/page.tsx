import { DataTable, WorkspaceLink } from "../../components/data-table";
import { ErrorBanner } from "../../components/error-banner";
import { Panel } from "../../components/panel";
import { RefreshButton } from "../../components/refresh-button";
import { getWorkItems } from "../../lib/console-api";

export const dynamic = "force-dynamic";

export default async function WorkItemsPage() {
  const rows = await getWorkItems();
  const normalized = rows.map((row) => ({
    workItemId: String((row.workItem as Record<string, unknown>)?.workItemId ?? ""),
    title: String((row.workItem as Record<string, unknown>)?.title ?? ""),
    repo: String((row.workItem as Record<string, unknown>)?.repo ?? ""),
    status: String((row.workItem as Record<string, unknown>)?.status ?? ""),
    contextPackId: String((row.contextPack as Record<string, unknown>)?.packId ?? ""),
  }));

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Workspace</span>
        <h1>Task Workspace</h1>
        <p>查看当前 WorkItem 列表，并进入单个任务的上下文、事件和发布详情。</p>
        <RefreshButton />
      </header>

      <ErrorBanner message={rows.length === 0 ? "当前未获取到 WorkItem 数据，可能是后端尚未写入。" : null} />

      <Panel title="Work Items" eyebrow="Backlog">
        <DataTable
          rows={normalized}
          emptyText="当前没有 WorkItem。"
          columns={[
            {
              key: "workItemId",
              label: "Work Item",
              render: (row) => <WorkspaceLink workItemId={String(row.workItemId ?? "")} />,
            },
            { key: "title", label: "Title" },
            { key: "repo", label: "Repo" },
            { key: "status", label: "Status" },
            { key: "contextPackId", label: "Context Pack" },
          ]}
        />
      </Panel>
    </div>
  );
}
