# -*- coding: utf-8 -*-
"""Week5 Day1 验收：能创建新项目、查看历史（API 通路 + 页面渲染）。

前置：后端 :8000 已启动。用法：python scripts/test_w5d1.py
"""
import json
import sys
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

BASE = "http://localhost:8000"


def req(method: str, path: str, body: dict | None = None):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None
    r = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r) as resp:
        return json.loads(resp.read().decode("utf-8"))


# 1. 创建新项目（模拟首页「开始新诊断」提交）
idea = "我想给健身房做一个会员约课小程序，支持团课预约和私教消课"
p = req("POST", "/api/projects",
        {"title": idea[:20], "raw_idea": idea})
pid = p["id"]
assert p["title"].startswith("我想给健身房做一个会员约课"), f"中文写入异常: {p['title']}"
assert p["status"] == "diagnosing"
print(f"[1] 创建新项目 OK：id={pid}, title={p['title']}, status={p['status']}")

# 2. 历史列表包含新项目且按时间倒序
items = req("GET", "/api/projects")["items"]
assert items[0]["id"] == pid, f"新项目不在列表首位: {items[0]['id']}"
assert any(i["id"] == pid for i in items)
print(f"[2] 历史列表 OK：共 {len(items)} 条，最新为 id={items[0]['id']}")

# 3. 项目详情可查
detail = req("GET", f"/api/projects/{pid}")
assert detail["raw_idea"] == idea
print("[3] 项目详情 OK：raw_idea 完整保留")

# 4. 清理测试数据
req("DELETE", f"/api/projects/{pid}")
assert all(i["id"] != pid for i in req("GET", "/api/projects")["items"])
print("[4] 清理 OK")

# 5. 前端页面渲染（Next.js dev server）
html = urllib.request.urlopen("http://localhost:3000").read().decode("utf-8")
assert "开始新诊断" in html and "把你的想法" in html, "首页未包含新诊断入口"
html2 = urllib.request.urlopen("http://localhost:3000/projects").read().decode("utf-8")
assert "历史项目" in html2
print("[5] 前端页面 OK：首页含「开始新诊断」入口，/projects 路由可达")

print("\n✅ Week5 Day1 验收通过（创建新项目 + 查看历史）")
