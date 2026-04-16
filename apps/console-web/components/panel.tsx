import { ReactNode } from "react";

type PanelProps = {
  title: string;
  eyebrow?: string;
  children: ReactNode;
};

export function Panel({ title, eyebrow, children }: PanelProps) {
  return (
    <section className="panel">
      <header className="panel-header">
        {eyebrow ? <span className="panel-eyebrow">{eyebrow}</span> : null}
        <h2>{title}</h2>
      </header>
      <div className="panel-body">{children}</div>
    </section>
  );
}
