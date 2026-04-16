import "./globals.css";

import type { Metadata } from "next";
import { ReactNode } from "react";

import { Sidebar } from "../components/sidebar";

export const metadata: Metadata = {
  title: "AI-DevOps Console",
  description: "Mission Control for AI-native product engineering workflows.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <div className="app-shell">
          <Sidebar />
          <main className="content-shell">{children}</main>
        </div>
      </body>
    </html>
  );
}
