"""方案 PDF 导出（服务端生成，手机零负担）。

演进史（为什么是 reportlab 而不是别的）：
- html2canvas+jsPDF 前端生成：手机端渲染长页面黑屏/卡死（实测踩坑）；
- window.print() 原生打印：国产安卓浏览器没有明显入口，客户找不到；
- 最终：方案数据本来就是结构化 JSON，用 reportlab 直接排版，
  纯 Python 无系统依赖（Windows 友好），手机只是下载一个现成文件。

中文：注册系统微软雅黑（msyh.ttc，subfontIndex=0），失败降级黑体 simhei.ttf。
"""

import io
import logging
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

logger = logging.getLogger(__name__)

_FONT_NAME: str | None = None


def _font() -> str:
    """注册并返回可用中文字体名（只做一次）。

    跨平台字体链（docker 部署到 Linux 后没有 Windows 字体）：
      1. 项目自带 backend/assets/fonts/*.ttc|ttf（最高优先，手动放置）
      2. Windows 本机开发字体（微软雅黑 ttc / 黑体 ttf）
      3. Docker 镜像里的 fonts-wqy-microhei（Dockerfile apt 安装）
    """
    global _FONT_NAME
    if _FONT_NAME:
        return _FONT_NAME
    from app.config import BASE_DIR

    builtin = sorted((BASE_DIR / "assets" / "fonts").glob("*.[to]t[cf]"))
    candidates: list[tuple[str, str, int | None]] = [(f.stem, str(f), None) for f in builtin]
    candidates += [
        ("MSYH", r"C:\Windows\Fonts\msyh.ttc", 0),      # Windows 开发机
        ("SIMHEI", r"C:\Windows\Fonts\simhei.ttf", None),
        ("WQY", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", 0),  # Linux/Docker
    ]
    for name, path, subfont in candidates:
        if not os.path.exists(path):
            continue
        try:
            if subfont is None:
                pdfmetrics.registerFont(TTFont(name, path))
            else:
                pdfmetrics.registerFont(TTFont(name, path, subfontIndex=subfont))
            _FONT_NAME = name
            logger.info("[pdf] 使用中文字体 %s（%s）", name, path)
            return name
        except Exception:
            logger.warning("[pdf] 字体 %s 注册失败", path, exc_info=True)
    _FONT_NAME = "Helvetica"  # 兜底：中文会缺字，但至少不崩
    logger.error("[pdf] 未找到任何中文字体，PDF 中文将显示为缺字方块")
    return _FONT_NAME


def _styles() -> dict[str, ParagraphStyle]:
    f = _font()
    base = dict(fontName=f, wordWrap="CJK")  # CJK 逐字换行，中文长句不溢出
    return {
        "title": ParagraphStyle("title", fontSize=17, leading=24, spaceAfter=2, **base),
        "meta": ParagraphStyle("meta", fontSize=9, leading=14, textColor=colors.HexColor("#666666"), **base),
        "h2": ParagraphStyle("h2", fontSize=13, leading=18, spaceBefore=14, spaceAfter=6,
                             textColor=colors.HexColor("#1d4ed8"), **base),
        "body": ParagraphStyle("body", fontSize=10.5, leading=17, spaceAfter=4, **base),
        "cell": ParagraphStyle("cell", fontSize=9.5, leading=14, **base),
        "cellHead": ParagraphStyle("cellHead", fontSize=9.5, leading=14, fontName=f,
                                   textColor=colors.white, wordWrap="CJK"),
        "footer": ParagraphStyle("footer", fontSize=8, leading=12, alignment=TA_CENTER,
                                 textColor=colors.HexColor("#999999"), **base),
    }


def _table(data: list[list], widths: list[float], st: dict) -> Table:
    """统一表格外观：蓝头白字 + 隔行浅灰。"""
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1d4ed8")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f5f7fb")]),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#d8dee9")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return t


def _yuan(n) -> str:
    return f"{n:,.0f}"


def build_solution_pdf(solution: dict) -> bytes:
    """把 solution JSON（requirements/plan/budget/feasibility）排版成 PDF bytes。

    字段全部容忍缺失（老项目 plan 可能不完整），缺哪段跳哪段。
    """
    st = _styles()
    plan = solution.get("plan") or {}
    budget = solution.get("budget") or {}
    feas = solution.get("feasibility") or {}
    req = solution.get("requirements") or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=18 * 4 / 3, rightMargin=18 * 4 / 3,
        topMargin=16 * 4 / 3, bottomMargin=16 * 4 / 3,
        title=plan.get("project_name", "AI 需求诊断方案"),
    )
    story: list = []
    W = doc.width  # 正文可用宽度

    # ── 标题区 ──
    story.append(Paragraph(plan.get("project_name", "AI 需求诊断方案"), st["title"]))
    meta = [f"生成于 {solution.get('generated_at', '')}"]
    if budget.get("total_min") is not None:
        meta.append(f"预算区间 ¥{_yuan(budget['total_min'])} ~ ¥{_yuan(budget['total_max'])}")
    story.append(Paragraph(" · ".join(m for m in meta if m), st["meta"]))
    story.append(Spacer(1, 6))

    # ── 需求确认 ──
    if req.get("summary"):
        story.append(Paragraph("需求确认", st["h2"]))
        story.append(Paragraph(req["summary"], st["body"]))

    # ── 业务方案 ──
    if plan.get("business_summary"):
        story.append(Paragraph("业务方案", st["h2"]))
        story.append(Paragraph(plan["business_summary"], st["body"]))
    modules = plan.get("core_business_modules") or []
    if modules:
        story.append(Spacer(1, 4))
        rows = [[Paragraph(h, st["cellHead"]) for h in ("优先级", "模块", "功能说明")]]
        for m in modules:
            rows.append([
                Paragraph(str(m.get("priority", "")), st["cell"]),
                Paragraph(str(m.get("name", "")), st["cell"]),
                Paragraph(str(m.get("description", "")), st["cell"]),
            ])
        story.append(_table(rows, [0.14 * W, 0.24 * W, 0.62 * W], st))

    # ── 技术方案 ──
    if plan.get("tech_architecture"):
        story.append(Paragraph("技术方案（技术选型、可行性）", st["h2"]))
        story.append(Paragraph(plan["tech_architecture"], st["body"]))
    stack = plan.get("tech_stack") or []
    if stack:
        story.append(Spacer(1, 4))
        rows = [[Paragraph(h, st["cellHead"]) for h in ("层级", "选型", "选择理由")]]
        for t in stack:
            rows.append([
                Paragraph(str(t.get("layer", "")), st["cell"]),
                Paragraph(str(t.get("choice", "")), st["cell"]),
                Paragraph(str(t.get("reason", "")), st["cell"]),
            ])
        story.append(_table(rows, [0.14 * W, 0.28 * W, 0.58 * W], st))

    # ── 实施排期 ──
    phases = plan.get("implementation_phases") or []
    if phases:
        story.append(Paragraph("项目排期", st["h2"]))
        for i, p in enumerate(phases, 1):
            story.append(Paragraph(f"<b>第 {i} 期</b>　{p}", st["body"]))

    # ── 预算明细 ──
    items = budget.get("line_items") or []
    if items:
        story.append(Paragraph("预算明细", st["h2"]))
        rows = [[Paragraph(h, st["cellHead"]) for h in ("计价项", "计价依据", "金额区间（元）")]]
        for it in items:
            rows.append([
                Paragraph(str(it.get("item", "")), st["cell"]),
                Paragraph(str(it.get("basis", "")), st["cell"]),
                Paragraph(f"{_yuan(it.get('min_amount', 0))} ~ {_yuan(it.get('max_amount', 0))}", st["cell"]),
            ])
        story.append(_table(rows, [0.3 * W, 0.45 * W, 0.25 * W], st))
        if budget.get("total_min") is not None:
            story.append(Spacer(1, 4))
            story.append(Paragraph(
                f"<b>合计：¥{_yuan(budget['total_min'])} ~ ¥{_yuan(budget['total_max'])}</b>"
                + (f"　（{budget['budget_match']}）" if budget.get("budget_match") else ""),
                st["body"]))
        for a in budget.get("assumptions") or []:
            story.append(Paragraph(f"· {a}", st["body"]))

    # ── 可行性评估 ──
    if feas:
        story.append(Paragraph("可行性评估", st["h2"]))
        overall = feas.get("overall", "")
        risk = feas.get("risk_level", "")
        if overall or risk:
            story.append(Paragraph(f"<b>{overall}</b>" + (f"（风险等级：{risk}）" if risk else ""), st["body"]))
        for label, key in (("技术", "tech_assessment"), ("工期", "schedule_assessment"), ("预算", "budget_assessment")):
            if feas.get(key):
                story.append(Paragraph(f"· <b>{label}</b>：{feas[key]}", st["body"]))
        for sg in feas.get("suggestions") or []:
            story.append(Paragraph(f"· 建议：{sg}", st["body"]))

    # ── 关键风险 ──
    risks = plan.get("key_risks") or []
    if risks:
        story.append(Paragraph("关键风险提示", st["h2"]))
        for r in risks:
            story.append(Paragraph(f"· {r}", st["body"]))

    def _footer(canvas, _doc):
        canvas.saveState()
        canvas.setFont(_font(), 8)
        canvas.setFillColor(colors.HexColor("#999999"))
        canvas.drawCentredString(A4[0] / 2, 10 * 4 / 3, "AI 需求诊断平台生成 · 本方案为估价参考，正式报价以合同为准")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    logger.info("[pdf] 方案 PDF 生成完成（%d KB）", buf.tell() // 1024)
    return buf.getvalue()
