import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: "AI 诊断 MVP",
  description: "AI 需求诊断与方案生成",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="zh-CN">
      <body
        style={{
          margin: 0,
          fontFamily:
            "-apple-system, 'PingFang SC', 'Microsoft YaHei', sans-serif",
          background: "#f5f6f8",
          color: "#1f2329",
        }}
      >
        {children}
      </body>
    </html>
  );
}
