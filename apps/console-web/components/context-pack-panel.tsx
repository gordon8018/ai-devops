export type ContextPack = {
  packId?: unknown;
  fileHints?: unknown;
  acceptanceCriteria?: unknown;
  repoScope?: unknown;
};

export function ContextPackPanel({ contextPack }: { contextPack: ContextPack }) {
  const fileHints = Array.isArray(contextPack.fileHints) ? (contextPack.fileHints as string[]) : [];
  const criteria = Array.isArray(contextPack.acceptanceCriteria) ? (contextPack.acceptanceCriteria as string[]) : [];
  const repoScope = Array.isArray(contextPack.repoScope) ? (contextPack.repoScope as string[]) : [];

  return (
    <div className="context-pack-section">
      <div>
        <p className="context-pack-label">Pack ID</p>
        <code style={{ fontSize: "13px", color: "var(--muted)" }}>{String(contextPack.packId ?? "-")}</code>
      </div>

      {repoScope.length > 0 ? (
        <div>
          <p className="context-pack-label">Repo Scope</p>
          <div className="file-hint-list">
            {repoScope.map((r) => <span key={r} className="file-hint">{r}</span>)}
          </div>
        </div>
      ) : null}

      {fileHints.length > 0 ? (
        <div>
          <p className="context-pack-label">File Hints</p>
          <div className="file-hint-list">
            {fileHints.map((f) => <span key={f} className="file-hint">{f}</span>)}
          </div>
        </div>
      ) : null}

      {criteria.length > 0 ? (
        <div>
          <p className="context-pack-label">Acceptance Criteria</p>
          <ul className="criteria-list">
            {criteria.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      ) : null}

      {fileHints.length === 0 && criteria.length === 0 ? (
        <p className="empty-state">Context Pack 暂无详情数据。</p>
      ) : null}
    </div>
  );
}
