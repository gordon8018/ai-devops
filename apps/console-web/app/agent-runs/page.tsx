import { DataTable, WorkspaceLink } from "../../components/data-table";
import { Panel } from "../../components/panel";
import { RefreshButton } from "../../components/refresh-button";
import { StatusBadge } from "../../components/status-badge";
import { getAgentRuns } from "../../lib/console-api";

export const dynamic = "force-dynamic";

function StepsProgress({ planned }: { planned: string[] }) {
  if (planned.length === 0) return <span className="subtle">—</span>;
  return (
    <span style={{ fontSize: "12px", color: "var(--muted)" }}>
      {planned.map((step, i) => (
        <span key={`${step}-${i}`} style={{ marginRight: "4px" }}>
          {i < planned.length - 1 ? `${step} →` : step}
        </span>
      ))}
    </span>
  );
}

export default async function AgentRunsPage() {
  const runs = await getAgentRuns();

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Execution</span>
        <h1>Agent Runs</h1>
        <p>查看所有 AgentRun 记录，包含执行模型、状态和计划步骤进度。</p>
        <RefreshButton />
      </header>

      <Panel title="Agent Runs" eyebrow={`${runs.length} runs`}>
        <DataTable
          rows={runs}
          emptyText="当前没有 Agent Run 记录。"
          columns={[
            { key: "runId", label: "Run ID" },
            {
              key: "workItemId",
              label: "Work Item",
              render: (row) => (
                <WorkspaceLink workItemId={String(row.workItemId ?? "")} />
              ),
            },
            { key: "agent", label: "Agent" },
            { key: "model", label: "Model" },
            {
              key: "status",
              label: "Status",
              render: (row) => <StatusBadge status={String(row.status ?? "-")} />,
            },
            {
              key: "plannedSteps",
              label: "Steps",
              render: (row) => (
                <StepsProgress
                  planned={
                    Array.isArray(row.plannedSteps) &&
                    row.plannedSteps.every((s) => typeof s === "string")
                      ? (row.plannedSteps as string[])
                      : []
                  }
                />
              ),
            },
          ]}
        />
      </Panel>
    </div>
  );
}
