import type { Metadata } from "next";

import "@copilotkit/react-ui/styles.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "诗行万里 | 唐宋诗歌证据工作台",
  description: "以可追溯史料查看诗人行迹、诗篇场景与唐宋意象差异。",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
