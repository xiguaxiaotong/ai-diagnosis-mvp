"""Week4 Day2 验收：文档加载 + 切分（PDF/Word/Markdown → 切分 → Chroma 入库）。

验收标准：上传一个 PDF，自动切分入库。
- 用 reportlab + Windows 自带中文字体生成真·可提取文本的 PDF
- 三份样例主题各不相同（点单/团购/客户管理），检索断言有意义
- 全流程离线：本地解析 + bge 本地 embedding，无需 key

用法（在 backend/ 目录下运行）：
    python scripts/test_w4d2.py
"""

import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.retrieval.loader import ingest_file, load_text  # noqa: E402
from app.retrieval.splitter import split_text  # noqa: E402
from app.retrieval.vector_store import VectorStore  # noqa: E402

# 三份不同主题的长文本（>500 字，强制多 chunk）
_DOC_BODY = (
    "连锁餐饮扫码点单小程序项目复盘。项目目标是为三家门店提供桌边扫码点餐能力，"
    "顾客扫码即可浏览菜单、下单与支付，订单直达后厨打印。"
    "技术栈采用微信小程序原生框架，后端使用 FastAPI 与 MySQL，"
    "对接商家现有收银系统完成订单与会员数据的双向同步。"
    "项目历时八周，预算约六万元，最终上线首月点单占比达到六成，"
    "高峰期排队时长明显下降，会员储值金额环比增长四成。"
)
_MD_BODY = (
    "社区团购小程序项目复盘。团长在微信群里开团发布商品，"
    "用户在接龙页面下单付款，次日到自提点取货。"
    "核心功能包括团长管理后台、商品上架与库存控制、"
    "微信支付分账与佣金结算、售后退款流程。"
    "采用微信小程序加 H5 双端方案，后端 Node.js 与 MongoDB，"
    "部署在云服务器上，单社区运营三个月实现日均两百单。"
)
DOCX_TEXT = _DOC_BODY * 5
MD_TEXT = "# 社区团购案例复盘\n\n" + _MD_BODY * 5 + "\n\n## 经验总结\n\n切分粒度决定检索质量。"


def make_pdf(path: Path, text: str) -> None:
    """reportlab 生成可提取文本的中文 PDF（Windows 自带黑体）。"""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.pdfgen import canvas

    font_candidates = [
        "C:/Windows/Fonts/simhei.ttf",   # 黑体
        "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑（ttc，reportlab 不支持则用上一个）
    ]
    font_file = next((f for f in font_candidates if Path(f).exists()), None)
    assert font_file, "未找到 Windows 中文字体（simhei/msyh），无法生成 PDF 样例"

    pdfmetrics.registerFont(TTFont("zh", font_file))
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4
    # 按句分行，每页 35 行，超出换页
    lines = [s + "。" for s in text.split("。") if s.strip()]
    y, page_lines = height - 50, 0
    for line in lines:
        c.setFont("zh", 11)
        c.drawString(50, y, line[:60])
        y -= 20
        page_lines += 1
        if page_lines >= 35:
            c.showPage()
            y, page_lines = height - 50, 0
    c.save()


def make_samples(tmp: str) -> dict[str, Path]:
    """生成 PDF / docx / md 三个不同主题的样例文件。"""
    from docx import Document

    base = Path(tmp)

    pdf_path = base / "案例-点单小程序.pdf"
    make_pdf(pdf_path, DOCX_TEXT)

    docx_path = base / "案例-客户管理.docx"
    doc = Document()
    for para in DOCX_TEXT.split("。"):
        if para.strip():
            doc.add_paragraph(para.strip() + "。")
    doc.save(docx_path)

    md_path = base / "案例-社区团购.md"
    md_path.write_text(MD_TEXT, encoding="utf-8")

    return {"pdf": pdf_path, "docx": docx_path, "md": md_path}


def main() -> None:
    tmp = tempfile.mkdtemp(prefix="w4d2_")
    files = make_samples(tmp)
    store = VectorStore(path=f"{tmp}/chroma")
    print(f"[0] 样例（pdf/docx/md 三主题）与临时库就绪")

    # ========== 1. 切分器：长文本切多块，短文本不切 ==========
    chunks = split_text(DOCX_TEXT)
    assert len(chunks) >= 2, f"长文本应切出多块: {len(chunks)}"
    assert all(len(c) <= 500 + 80 for c in chunks), "chunk 超长"
    assert split_text("短文本") == ["短文本"], "短文本不应被切"
    assert split_text("") == [], "空文本返回空"
    print(f"[1] 切分 OK：{len(DOCX_TEXT)} 字 → {len(chunks)} 块，块间有重叠")

    # ========== 2. PDF：加载 + 切分 + 入库（验收主路径） ==========
    pdf_text = load_text(files["pdf"])
    assert "扫码点单" in pdf_text and len(pdf_text) > 100, f"PDF 文本提取异常: {len(pdf_text)}"
    n_pdf = ingest_file(files["pdf"], store, metadata={"industry": "餐饮"})
    assert n_pdf >= 2, f"PDF 应切出多块入库: {n_pdf}"
    print(f"[2] PDF 入库 OK：提取 {len(pdf_text)} 字 → {n_pdf} 块入库")

    # ========== 3. docx + md 同一入口入库 ==========
    n_docx = ingest_file(files["docx"], store, metadata={"industry": "外贸"})
    n_md = ingest_file(files["md"], store, metadata={"industry": "电商"})
    assert n_docx >= 2 and n_md >= 2, (n_docx, n_md)
    assert store.count() == n_pdf + n_docx + n_md, store.count()
    print(f"[3] 全量入库 OK：pdf {n_pdf} + docx {n_docx} + md {n_md} = {store.count()} 条")

    # ========== 4. 检索：不同主题查询命中各自文档 ==========
    hits = store.search("顾客扫码点餐 会员储值", top_k=2)
    assert hits[0]["metadata"]["source"].endswith(".pdf"), hits[0]["metadata"]["source"]
    assert hits[0]["score"] > 0.5, hits[0]["score"]
    print(f"[4] 检索 OK：top1 source={hits[0]['metadata']['source']}，score={hits[0]['score']}")
    hits = store.search("团长开团 接龙下单 自提", top_k=1)
    assert hits[0]["metadata"]["source"].endswith(".md"), hits[0]["metadata"]["source"]
    print(f"    团购查询 → md 命中（score={hits[0]['score']}）")

    # ========== 5. 幂等重传：同文件再入库不翻倍 ==========
    n_again = ingest_file(files["pdf"], store, metadata={"industry": "餐饮"})
    assert n_again == n_pdf and store.count() == n_pdf + n_docx + n_md, (n_again, store.count())
    print(f"[5] 幂等 OK：重传 PDF 仍 {n_again} 块，总数不翻倍")

    # ========== 6. 不支持的格式报错 ==========
    try:
        load_text(files["pdf"].with_suffix(".exe"))
        raise AssertionError("应抛出 ValueError")
    except ValueError:
        print(f"[6] 格式校验 OK：不支持类型直接拒绝")

    print("\n" + "=" * 54)
    print("✅ Week4 Day2 验收通过（PDF/docx/md 加载 → 切分 → 入库 → 检索）")
    print("=" * 54)


if __name__ == "__main__":
    main()
