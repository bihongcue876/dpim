"""检索文本工具：查询切词 + 多关键词 LIKE 计分（纯标准库，零依赖）。

中文场景 FTS5 大多不命中而走 LIKE 降级；旧实现按「整串 LIKE」召回，
多词查询（如 "Python 异步"）基本全灭。这里按「连续中文段 + 英文单词/数字」
切词，多词 OR 召回 + 命中词数/位置综合计分，显著改善中文/混合查询召回。
"""

from __future__ import annotations

import re

# 高频虚词/停用词（中英），过滤后减少无效召回与 SQL 膨胀
_STOPWORDS = {
    "的", "了", "是", "在", "和", "与", "及", "或", "吗", "呢", "啊", "吧",
    "这", "那", "你", "我", "他", "她", "它", "们", "个", "什么", "怎么",
    "如何", "为什么", "什么是", "一个", "这个", "那个", "没有", "不是", "就是",
    "为", "对", "从", "到", "用", "被", "把", "让", "给", "就", "都",
    "也", "很", "最", "还", "又", "再", "能", "会", "要", "想", "说", "做",
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "at", "for",
    "with", "is", "are", "was", "were", "be", "how", "what", "why", "when",
    "where", "which", "who", "do", "does", "did", "it", "its",
}

# 单次查询最多参与匹配的词数：防 SQL OR 子句膨胀 + 防噪声词稀释排序
_MAX_TOKENS = 8


def tokenize_query(query: str) -> list[str]:
    """查询切词：英文单词/数字 + 连续中文段；过滤停用词与单字符非数字；上限 8 词。"""
    raw = re.findall(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+", query)
    tokens: list[str] = []
    for t in raw:
        low = t.lower()
        if low in _STOPWORDS:
            continue
        if len(t) < 2 and not t.isdigit():
            continue
        tokens.append(t)
    return tokens[:_MAX_TOKENS]


def like_rank_multi(tokens: list[str], title: str, content: str) -> float:
    """多关键词相关度：rank 越小越相关（与 FTS5 rank 语义对齐）。

    - 标题命中权重大于内容命中（1.0 vs 0.5）
    - 多词时命中词数主导排序（位置仅微调），避免长文本位置权重盖过词数
    - 单个 token 时严格复用旧 like_rank 公式，行为完全一致
    """
    if len(tokens) == 1:
        from core.event_store import like_rank

        return like_rank(tokens[0], title, content)

    rank = 0.0
    t = (title or "").lower()
    c = (content or "").lower()
    for tok in tokens:
        low = tok.lower()
        tp = t.find(low)
        if tp >= 0:
            rank += -1.0 / (1.0 + tp / 50.0)
            continue
        cp = c.find(low)
        if cp >= 0:
            rank += -0.5 / (1.0 + cp / 50.0)
    return rank
