"""Day2 测试脚本：P5 模型客户端验证。

用法（在 backend/ 目录下运行）：
    python scripts/test_day2.py embed     # 只测 Embedding（无需 key）
    python scripts/test_day2.py chat      # 只测流式对话（需要 DEEPSEEK_API_KEY）
    python scripts/test_day2.py all       # 全部测试
"""

import sys
import time
from pathlib import Path

# Windows 控制台 GBK 编码兼容：强制 stdout 走 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

# 保证可以从 backend/ 目录直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def test_embedding() -> bool:
    """测试 bge-small 本地 Embedding：文本转向量 + 相似度。"""
    print("=" * 50)
    print("测试 1: bge-small Embedding（本地，无需 key）")
    print("=" * 50)

    from app.infra.model_client import embedding_client

    t0 = time.perf_counter()
    docs = [
        "我想给餐饮店做一个扫码点单小程序",
        "帮我开发一个客户关系管理CRM系统",
        "今天天气不错，适合出门散步",
    ]
    doc_vecs = embedding_client.embed_documents(docs)
    print(f"文档向量数量: {len(doc_vecs)}, 维度: {len(doc_vecs[0])}")
    print(f"首次加载+编码耗时: {time.perf_counter() - t0:.2f}s")

    # 查询向量（加检索指令前缀）
    query = "外卖店的线上点单系统"
    q_vec = embedding_client.embed_query(query)
    print(f"查询向量维度: {len(q_vec)}")

    # 余弦相似度（向量已归一化，点积即相似度）
    def cosine(a, b):
        return sum(x * y for x, y in zip(a, b))

    print(f"\n查询「{query}」与各文档相似度:")
    scores = sorted(zip(docs, [cosine(q_vec, v) for v in doc_vecs]), key=lambda x: -x[1])
    for doc, score in scores:
        print(f"  {score:.4f}  {doc}")

    assert len(doc_vecs[0]) == 512, "bge-small-zh-v1.5 应输出 512 维"
    print("\n✅ Embedding 测试通过")
    return True


def test_chat_stream() -> bool:
    """测试 DeepSeek 流式对话（需要 DEEPSEEK_API_KEY）。"""
    print("=" * 50)
    print("测试 2: DeepSeek 流式对话（需要 key）")
    print("=" * 50)

    from app.config import DEEPSEEK_API_KEY
    from app.infra.model_client import chat_client

    if not DEEPSEEK_API_KEY or "你的" in DEEPSEEK_API_KEY:
        print("❌ 未配置 DEEPSEEK_API_KEY")
        print("   请在项目根目录 .env 中填入: DEEPSEEK_API_KEY=sk-xxx")
        return False

    messages = [
        {"role": "system", "content": "你是一个简洁的助手，回答不超过30个字。"},
        {"role": "user", "content": "用一句话介绍什么是AI Agent"},
    ]

    t0 = time.perf_counter()
    first_token_at = None
    full_text = []
    print("流式输出: ", end="", flush=True)
    for chunk in chat_client.stream_chat(messages):
        if first_token_at is None:
            first_token_at = time.perf_counter() - t0
        print(chunk, end="", flush=True)
        full_text.append(chunk)
    print()

    text = "".join(full_text)
    print(f"\n首 token 延迟: {first_token_at:.2f}s, 总耗时: {time.perf_counter() - t0:.2f}s")
    print(f"完整回复长度: {len(text)} 字")
    assert len(text) > 0, "流式回复不能为空"
    print("\n✅ 流式对话测试通过")
    return True


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "all"
    results = {}
    if mode in ("embed", "all"):
        results["embedding"] = test_embedding()
    if mode in ("chat", "all"):
        results["chat"] = test_chat_stream()

    print("\n" + "=" * 50)
    for name, ok in results.items():
        print(f"{'✅' if ok else '❌'} {name}")
    failed = [n for n, ok in results.items() if not ok]
    sys.exit(1 if failed else 0)
