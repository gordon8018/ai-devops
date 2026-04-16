import { DataTable } from "../../components/data-table";
import { ErrorBanner } from "../../components/error-banner";
import { Panel } from "../../components/panel";
import { RefreshButton } from "../../components/refresh-button";
import { getGovernanceConsole } from "../../lib/console-api";
import { evalGovernanceCards, resourceErrorMessage } from "../../lib/console-data.mjs";

export const dynamic = "force-dynamic";

export default async function GovernancePage() {
  const fetched = await getGovernanceConsole();
  const data = fetched ?? {
    legacyEntrypoints: { total: 0, byEntrypoint: {} },
    workItemSources: {},
    cutoverReadiness: { ready: false, blockingReasons: [] },
    auditSummary: { total: 0, byAction: {} },
  };
  const errorMessage = resourceErrorMessage(fetched, "Governance Console");
  const governanceCards = evalGovernanceCards(data as Record<string, unknown>);
  const legacyEntrypointRows = Object.entries(
    ((data.legacyEntrypoints as Record<string, unknown>)?.byEntrypoint as Record<string, number>) ?? {},
  ).map(([entrypoint, count]) => ({ entrypoint, count }));
  const sourceRows = Object.entries((data.workItemSources as Record<string, number>) ?? {}).map(([source, count]) => ({
    source,
    count,
  }));
  const auditRows = Object.entries((data.auditSummary as Record<string, unknown>)?.byAction ?? {}).map(
    ([action, count]) => ({ action, count }),
  );
  const blockingRows = Array.isArray((data.cutoverReadiness as Record<string, unknown>)?.blockingReasons)
    ? (((data.cutoverReadiness as Record<string, unknown>)?.blockingReasons as string[]) ?? []).map((reason) => ({
        reason,
      }))
    : [];

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Governance</span>
        <h1>Governance Console</h1>
        <p>集中查看 legacy 入口使用、切流 readiness 和治理审计摘要。</p>
        <RefreshButton />
      </header>

      <ErrorBanner message={errorMessage} />

      <Panel title="Governance Summary" eyebrow="Cutover">
        <div className="pill-row">
          {governanceCards.map((card) => (
            <span key={card.label} className="pill">
              {card.label}: {card.value}
            </span>
          ))}
        </div>
      </Panel>

      <Panel title="Legacy Entrypoints" eyebrow="Compatibility">
        <DataTable
          rows={legacyEntrypointRows}
          emptyText="当前没有 legacy 入口调用。"
          columns={[
            { key: "entrypoint", label: "Entrypoint" },
            { key: "count", label: "Count" },
          ]}
        />
      </Panel>

      <Panel title="Work Item Sources" eyebrow="Adoption">
        <DataTable
          rows={sourceRows}
          emptyText="当前没有 work item 来源数据。"
          columns={[
            { key: "source", label: "Source" },
            { key: "count", label: "Count" },
          ]}
        />
      </Panel>

      <Panel title="Audit Actions" eyebrow="Audit">
        <DataTable
          rows={auditRows}
          emptyText="当前没有治理审计记录。"
          columns={[
            { key: "action", label: "Action" },
            { key: "count", label: "Count" },
          ]}
        />
      </Panel>

      <Panel title="Blocking Reasons" eyebrow="Readiness">
        <DataTable
          rows={blockingRows}
          emptyText="当前没有切流阻塞项。"
          columns={[{ key: "reason", label: "Reason" }]}
        />
      </Panel>
    </div>
  );
}
