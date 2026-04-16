import { DataTable } from "../../components/data-table";
import { ErrorBanner } from "../../components/error-banner";
import { Panel } from "../../components/panel";
import { RefreshButton } from "../../components/refresh-button";
import { getEvalConsole } from "../../lib/console-api";
import { evalGovernanceCards, resourceErrorMessage } from "../../lib/console-data.mjs";

export const dynamic = "force-dynamic";

export default async function EvalsPage() {
  const fetched = await getEvalConsole();
  const data = fetched ?? { taskStatusCounts: {}, alertCount: 0, totalEvents: 0, governance: {} };
  const rows = Object.entries((data.taskStatusCounts as Record<string, number>) ?? {}).map(([status, count]) => ({
    status,
    count,
  }));
  const governanceCards = evalGovernanceCards(data.governance as Record<string, unknown>);
  const legacyEntrypointRows = Object.entries(
    ((data.governance as Record<string, unknown>)?.legacyEntrypoints as Record<string, unknown>)?.byEntrypoint ??
      {},
  ).map(([entrypoint, count]) => ({ entrypoint, count }));
  const blockingReasons = Array.isArray(
    ((data.governance as Record<string, unknown>)?.cutoverReadiness as Record<string, unknown>)?.blockingReasons,
  )
    ? ((((data.governance as Record<string, unknown>)?.cutoverReadiness as Record<string, unknown>)
        ?.blockingReasons as string[]) ?? [])
    : [];
  const errorMessage = resourceErrorMessage(fetched, "Eval Console");

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Eval</span>
        <h1>Eval Console</h1>
        <p>基于当前事件流查看状态分布、告警量和执行健康度。</p>
        <RefreshButton />
      </header>

      <ErrorBanner message={errorMessage} />

      <Panel title="Eval Summary" eyebrow="Signals">
        <div className="pill-row">
          <span className="pill">Alerts: {String(data.alertCount ?? 0)}</span>
          <span className="pill">Events: {String(data.totalEvents ?? 0)}</span>
        </div>
      </Panel>

      <Panel title="Governance Summary" eyebrow="Cutover">
        <div className="pill-row">
          {governanceCards.map((card) => (
            <span key={card.label} className="pill">
              {card.label}: {card.value}
            </span>
          ))}
        </div>
      </Panel>

      <Panel title="Task Status Distribution" eyebrow="Execution">
        <DataTable
          rows={rows}
          emptyText="当前没有 eval 统计。"
          columns={[
            { key: "status", label: "Status" },
            { key: "count", label: "Count" },
          ]}
        />
      </Panel>

      <Panel title="Legacy Entrypoints" eyebrow="Governance">
        <DataTable
          rows={legacyEntrypointRows}
          emptyText="当前没有旧入口调用记录。"
          columns={[
            { key: "entrypoint", label: "Entrypoint" },
            { key: "count", label: "Count" },
          ]}
        />
      </Panel>

      <Panel title="Cutover Blocking Reasons" eyebrow="Readiness">
        <DataTable
          rows={blockingReasons.map((reason) => ({ reason }))}
          emptyText="当前没有切流阻塞项。"
          columns={[{ key: "reason", label: "Reason" }]}
        />
      </Panel>
    </div>
  );
}
