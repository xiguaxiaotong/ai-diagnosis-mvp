"""W8 Day5：understand 黄金集评估（真实 DeepSeek，非 stub）。

数据源 golden_cases.json：30 条种子案例库 CSV 真实需求（按行内结构化
字段渲染成口语化输入，模板固定可复现）。逐条真实跑 understand_node——
prompt → LLM 抽取 → extract_json → ProjectRequirements 校验 →
budget_tier 分类全链路，然后对照 CSV 结构化真值算字段级命中率。

命中口径：
- 类型      business_type/project_title/core_features 合并文本包含场景关键词
- 预算      parse_budget(mentioned_budget) 落在 CSV [budget_min, budget_max]
- 上线周期  mentioned_deadline 解析出的周数落在 CSV [weeks_lo, weeks_hi]
- 核心功能  真值功能命中（子串或相似度≥0.4）占比 ≥ 50%
- 联系方式  CSV 无真值，不评估（见 BASELINE.md 说明）

基线对比：baseline.json 记录各字段基线命中数，本跑低于基线 → 失败
（改 prompt 前后各跑一遍，命中率退化立即可见）。首次跑没有 baseline.json
时只出报告不设门槛（跑完把数字写进 baseline.json + BASELINE.md）。

用法（backend/ 下）：
    python -m pytest tests/golden -q          # 全量（~1-2 分钟，约 0.1 元）
    python -m pytest tests/golden -q -m llm   # 同上
"""

import difflib
import json
import re
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))  # backend/

from app.agent.nodes.understand import understand_node  # noqa: E402
from app.agent.nodes.budget import parse_budget  # noqa: E402
from app.config import DEEPSEEK_API_KEY  # noqa: E402

pytestmark = [pytest.mark.llm, pytest.mark.slow]

CASES = json.loads((HERE / "golden_cases.json").read_text(encoding="utf-8"))

_CN_NUM = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6,
           "七": 7, "八": 8, "九": 9, "十": 10, "半": 0.5}


def _parse_weeks(text: str | None) -> list[float]:
    """从工期表述解析周数（数字 + 中文数字；'1-2周' → [1, 2]）。"""
    if not text:
        return []
    out: list[float] = []
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s*周", text):
        out.append(float(m.group(1)))
    for cn, v in _CN_NUM.items():
        if f"{cn}周" in text or f"{cn} 个周" in text:
            out.append(v)
    return out


def _feature_hit(truth: str, extracted_text: str) -> bool:
    """真值功能是否被抽到：子串 或 序列相似度 ≥ 0.4（容忍措辞重组）。"""
    if not truth:
        return False
    if truth in extracted_text:
        return True
    for ex in extracted_text.split("、"):
        if difflib.SequenceMatcher(None, truth, ex).ratio() >= 0.4:
            return True
    return False


@pytest.mark.skipif(not DEEPSEEK_API_KEY, reason="需要 DEEPSEEK_API_KEY")
def test_understand_golden():
    # Windows GBK 控制台打不出 ✓/✗（旧脚本同款处理）
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    report = []
    hits = {"type": 0, "budget": 0, "weeks": 0, "features": 0}
    extracted_ok = 0

    for case in CASES:
        exp = case["expect"]
        delta = understand_node({
            "raw_idea": case["input"],
            "messages": [{"role": "user", "content": case["input"]}],
            "clarify_round": 0,
        })
        req = delta.get("requirements") or {}
        if not req or delta.get("error"):
            report.append((case["id"], "❌ 抽取失败", ""))
            continue
        extracted_ok += 1

        combined = "".join(filter(None, [
            req.get("business_type", ""), req.get("project_title", ""),
            "".join(req.get("core_features") or []),
        ]))
        type_hit = exp["type_kw"] in combined

        amount = parse_budget(req.get("mentioned_budget"))
        budget_hit = (amount is not None
                      and exp["budget_min"] <= amount <= exp["budget_max"])

        weeks = _parse_weeks(req.get("mentioned_deadline"))
        weeks_hit = bool(exp["weeks_lo"] is not None and weeks
                         and any(exp["weeks_lo"] <= w <= exp["weeks_hi"]
                                 for w in weeks))

        ex_feats = "、".join(req.get("core_features") or [])
        n_hit = sum(_feature_hit(f, ex_feats) for f in exp["features"])
        feats_hit = bool(exp["features"]) and n_hit * 2 >= len(exp["features"])

        for field, ok in (("type", type_hit), ("budget", budget_hit),
                          ("weeks", weeks_hit), ("features", feats_hit)):
            if ok:
                hits[field] += 1
        report.append((case["id"],
                       f"类型{'✓' if type_hit else '✗'} "
                       f"预算{'✓' if budget_hit else '✗'}"
                       f"({req.get('mentioned_budget')!r}→{amount}) "
                       f"工期{'✓' if weeks_hit else '✗'}"
                       f"({req.get('mentioned_deadline')!r}→{weeks}) "
                       f"功能{'✓' if feats_hit else '✗'}({n_hit}/{len(exp['features'])})",
                       ""))

    n = len(CASES)
    print(f"\n{'=' * 62}")
    print(f"understand 黄金集评估：{n} 条（抽取成功 {extracted_ok}）")
    for field, cn in (("type", "类型"), ("budget", "预算"),
                      ("weeks", "上线周期"), ("features", "核心功能")):
        print(f"  {cn:<6} {hits[field]}/{n}")
    print(f"{'=' * 62}")
    for rid, line, _ in report:
        print(f"  #{rid} {line}")

    # 抽取本身不能炸（LLM 输出必须可解析可校验）
    assert extracted_ok == n, f"有 {n - extracted_ok} 条抽取失败"

    baseline_file = HERE / "baseline.json"
    if baseline_file.exists():
        baseline = json.loads(baseline_file.read_text(encoding="utf-8"))
        for field, thresh in baseline.items():
            assert hits[field] >= thresh, (
                f"{field} 命中率退化：{hits[field]}/{n} < 基线 {thresh}/{n}"
                f"（改 prompt 引入的回归？复核后更新 baseline.json + BASELINE.md）")
