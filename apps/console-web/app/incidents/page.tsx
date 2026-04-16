import { DataTable } from "../../components/data-table";
import { ErrorBanner } from "../../components/error-banner";
import { Panel } from "../../components/panel";
import { RefreshButton } from "../../components/refresh-button";
import { getIncidentConsole } from "../../lib/console-api";
import { resourceErrorMessage } from "../../lib/console-data.mjs";

export const dynamic = "force-dynamic";

export default async function IncidentsPage() {
  const fetched = await getIncidentConsole();
  const data = fetched ?? { total: 0, bySeverity: {}, items: [] };
  const items = Array.isArray(data.items) ? data.items : [];
  const errorMessage = resourceErrorMessage(fetched, "Incident Console");

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Incident</span>
        <h1>Incident Console</h1>
        <p>查看事故聚类、严重性分布和关闭状态。</p>
        <RefreshButton />
      </header>

      <ErrorBanner message={errorMessage} />

      <Panel title="Severity Summary" eyebrow="Triage">
        <div className="pill-row">
          <span className="pill">Total: {String(data.total ?? 0)}</span>
          {Object.entries((data.bySeverity as Record<string, number>) ?? {}).map(([severity, count]) => (
            <span className="pill" key={severity}>
              {severity}: {count}
            </span>
          ))}
        </div>
      </Panel>

      <Panel title="Incidents" eyebrow="Cluster">
        <DataTable
          rows={items as Record<string, unknown>[]}
          emptyText="当前没有 incident 数据。"
          columns={[
            { key: "incidentId", label: "Incident" },
            { key: "severity", label: "Severity" },
            { key: "status", label: "Status" },
            { key: "message", label: "Message" },
          ]}
        />
      </Panel>
    </div>
  );
}
