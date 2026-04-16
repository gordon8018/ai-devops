import Link from "next/link";

import { consoleNavItems } from "../lib/navigation.mjs";

export function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="brand-kicker">AI-DevOps</span>
        <h1>Console</h1>
        <p>面向产品交付的智能体工程控制台</p>
      </div>
      <nav className="nav">
        {consoleNavItems.map((item) => (
          <Link key={item.id} href={item.href} className="nav-link">
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>
    </aside>
  );
}
