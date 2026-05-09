import { Panel } from "../../../components/panel";
import { RefreshButton } from "../../../components/refresh-button";
import { StatusBadge } from "../../../components/status-badge";
import { getPlanDetail } from "../../../lib/console-api";

export const dynamic = "force-dynamic";

type PlanStep = {
  id?: unknown;
  name?: unknown;
  description?: unknown;
  status?: unknown;
  depends_on?: unknown;
};

export default async function PlanDetailPage({
  params,
}: {
  params: Promise<{ planId: string }>;
}) {
  const { planId } = await params;
  const fetched = await getPlanDetail(planId);

  if (!fetched) {
    return (
      <div className="page">
        <header className="page-header">
          <span className="page-kicker">Plan</span>
          <h1>Plan Detail</h1>
          <p className="empty-state">未找到 Plan：{planId}</p>
        </header>
      </div>
    );
  }

  const plan = (fetched.plan as Record<string, unknown> | undefined) ?? fetched;
  const steps: PlanStep[] = Array.isArray(plan.subtasks)
    ? (plan.subtasks as PlanStep[])
    : Array.isArray(plan.steps)
    ? (plan.steps as PlanStep[])
    : [];

  const status = String(plan.status ?? "unknown");
  const repo = String(plan.repo ?? "-");
  const objective = String(plan.objective ?? plan.title ?? "-");

  return (
    <div className="page">
      <header className="page-header">
        <span className="page-kicker">Plan</span>
        <h1>{String(plan.title ?? planId)}</h1>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            flexWrap: "wrap",
            marginTop: "8px",
          }}
        >
          <StatusBadge status={status} />
          <span className="subtle">repo: {repo}</span>
        </div>
        <RefreshButton />
      </header>

      <Panel title="Objective" eyebrow="Goal">
        <p style={{ margin: 0, lineHeight: 1.6 }}>{objective}</p>
      </Panel>

      <Panel title={`Steps (${steps.length})`} eyebrow="Execution Plan">
        {steps.length === 0 ? (
          <p className="empty-state">该 Plan 暂无步骤数据。</p>
        ) : (
          <ol className="plan-steps">
            {steps.map((step, i) => (
              <li key={String(step.id ?? i)} className="plan-step">
                <div className="plan-step-number">{i + 1}</div>
                <div className="plan-step-body">
                  <div
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      flexWrap: "wrap",
                    }}
                  >
                    <span className="plan-step-title">
                      {String(step.name ?? step.id ?? `Step ${i + 1}`)}
                    </span>
                    {step.status ? <StatusBadge status={String(step.status)} /> : null}
                  </div>
                  {step.description ? (
                    <p className="plan-step-description">{String(step.description)}</p>
                  ) : null}
                  {Array.isArray(step.depends_on) && step.depends_on.length > 0 ? (
                    <p className="plan-step-description">
                      depends on: {(step.depends_on as unknown[]).map(String).join(", ")}
                    </p>
                  ) : null}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <Panel title="Raw Plan JSON" eyebrow="Debug">
        <pre className="code-block">{JSON.stringify(plan, null, 2)}</pre>
      </Panel>
    </div>
  );
}
