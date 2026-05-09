import { StatusBadge } from "./status-badge";

type TimelineEvent = {
  type?: unknown;
  source?: unknown;
  timestamp?: unknown;
  data?: unknown;
};

function formatTimestamp(ts: unknown): string {
  const n = Number(ts);
  if (!n) return "";
  return new Date(n).toLocaleString("zh-CN", { hour12: false });
}

export function Timeline({
  events,
  emptyText,
}: {
  events: TimelineEvent[];
  emptyText: string;
}) {
  if (events.length === 0) {
    return <p className="empty-state">{emptyText}</p>;
  }

  const sorted = [...events].sort(
    (a, b) => Number(a.timestamp ?? 0) - Number(b.timestamp ?? 0)
  );

  return (
    <ol className="timeline-v" style={{ listStyle: "none", padding: 0, margin: 0 }}>
      {sorted.map((event, i) => {
        const status = String(
          (event.data as Record<string, unknown>)?.status ?? ""
        );
        return (
          <li key={i} className="timeline-entry">
            <div className="timeline-dot" />
            <div className="timeline-entry-body">
              <div style={{ display: "flex", alignItems: "center", gap: "8px", flexWrap: "wrap" }}>
                <span className="timeline-event-type">{String(event.type ?? "event")}</span>
                {status ? <StatusBadge status={status} /> : null}
                {event.timestamp ? (
                  <span className="timeline-event-source">{formatTimestamp(event.timestamp)}</span>
                ) : null}
              </div>
              {event.source ? (
                <span className="timeline-event-source">source: {String(event.source)}</span>
              ) : null}
              {event.data ? (
                <pre className="timeline-event-data">{JSON.stringify(event.data, null, 2)}</pre>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
