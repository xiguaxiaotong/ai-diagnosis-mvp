# -*- coding: utf-8 -*-
"""Week5 Day5 验收：UI 打磨 + 响应式适配 + 错误处理。

验收标准：全部页面可渲染；移动端 viewport meta 生效；
错误处理（重试/二次确认/输入防缩放）代码就位。
前置：前端 :3000 已启动（页面渲染检查）；后端 :8000 已启动（数据通路）。
用法：python scripts/test_w5d5.py
"""
import re
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

FRONT = "http://localhost:3000"
BACK = "http://localhost:8000"


def fetch(url: str) -> str:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return resp.read().decode("utf-8")


def main() -> None:
    # 1. 后端健康
    assert '"ok"' in fetch(BACK + "/api/health"), "后端未启动"
    print("[1] 后端 :8000 健康 OK")

    # 2. 四个页面全部 200 且为客户端渲染壳
    pages = {"/": "首页", "/projects": "历史项目", "/chat/1": "聊天页", "/project/1": "方案页"}
    for path, name in pages.items():
        html = fetch(FRONT + path)
        assert 'id="__next"' in html or "next" in html, f"{name} 渲染异常"
        print(f"[2] {name} {path} → 200 OK")

    # 3. 移动端 viewport meta（device-width + viewport-fit:cover）
    html = fetch(FRONT + "/")
    m = re.search(r'<meta name="viewport" content="([^"]+)"', html)
    assert m, "缺少 viewport meta"
    vp = m.group(1)
    assert "device-width" in vp, f"viewport 缺 device-width: {vp}"
    assert "viewport-fit=cover" in vp, f"viewport 缺 viewport-fit=cover: {vp}"
    print(f"[3] 移动端 viewport OK（{vp}）")

    # 4. 错误处理与移动适配代码就位（源码级断言）
    def src(path: str) -> str:
        with open(path, encoding="utf-8") as f:
            return f.read()

    home = src(r"D:\ai-diagnosis-mvp\frontend\app\page.tsx")
    assert "fontSize: 16" in home and "minHeight: 48" in home, "首页输入/按钮适配缺失"
    assert "clamp(" in home, "首页响应式字号缺失"

    projects = src(r"D:\ai-diagnosis-mvp\frontend\app\projects\page.tsx")
    assert "window.confirm" in projects, "删除二次确认缺失"
    assert "重试" in projects, "错误重试按钮缺失"

    chat = src(r"D:\ai-diagnosis-mvp\frontend\app\chat\[id]\page.tsx")
    assert "100dvh" in chat, "聊天页动态视口高度缺失"
    assert "safe-area-inset-bottom" in chat, "聊天页底部安全区缺失"

    proj = src(r"D:\ai-diagnosis-mvp\frontend\app\project\[id]\page.tsx")
    assert proj.count("overflowX") >= 3, "方案页表格横向滚动包裹不足 3 处"
    assert "safe-area-inset-bottom" in proj, "方案页操作栏安全区缺失"

    layout = src(r"D:\ai-diagnosis-mvp\frontend\app\layout.tsx")
    assert "viewportFit" in layout and "WebkitTapHighlightColor" in layout, \
        "layout viewport/tap-highlight 缺失"
    print("[4] 移动适配与错误处理代码断言 OK（16px 输入 / 44px 触控 / dvh / safe-area / 滚动表格 / 重试 / 二次确认）")

    print("\n=== Week5 Day5 验收全部通过 ===")


if __name__ == "__main__":
    main()
