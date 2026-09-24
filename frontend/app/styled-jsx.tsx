"use client";

import { useState, type ReactNode } from "react";
import { useServerInsertedHTML } from "next/navigation";
import { StyleRegistry, createStyleRegistry } from "styled-jsx";

/** App Router 的 styled-jsx 注册器（必须放在 client 文件里再被 Server 布局引用），
 *  把 hydration 前插入的 <style jsx> 样式流式注入 SSR HTML，
 *  避免首帧无布局、hydration 后闪变 */
export function StyledJsx({ children }: { children: ReactNode }) {
  const [registry] = useState(() => createStyleRegistry());
  useServerInsertedHTML(() => {
    const styles = registry.styles();
    registry.flush();
    return <>{styles}</>;
  });
  return <StyleRegistry registry={registry}>{children}</StyleRegistry>;
}
