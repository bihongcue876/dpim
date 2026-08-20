"""text_utils：查询切词 + 多关键词计分"""

from core.event_store import like_rank
from core.text_utils import like_rank_multi, tokenize_query


class TestTokenizeQuery:
    def test_english_words(self):
        assert tokenize_query("Python async") == ["Python", "async"]

    def test_chinese_and_english_mix(self):
        assert tokenize_query("Python 异步编程") == ["Python", "异步编程"]

    def test_stopwords_filtered(self):
        assert tokenize_query("什么是 异步") == ["异步"]

    def test_single_char_filtered(self):
        # 单字符中文/字母（非数字）过滤
        assert tokenize_query("图 a") == []

    def test_token_cap(self):
        tokens = tokenize_query("one two three four five six seven eight nine ten")
        assert len(tokens) == 8

    def test_punctuation_ignored(self):
        assert tokenize_query("Python, 异步！") == ["Python", "异步"]


class TestLikeRankMulti:
    def test_title_priority(self):
        title = like_rank_multi(["异步"], "异步编程入门", "无相关内容")
        content = like_rank_multi(["异步"], "其他标题", "我学习异步编程")
        assert title < content  # 标题命中排前（rank 更小）

    def test_more_tokens_more_relevant(self):
        single = like_rank_multi(["异步"], "", "Python 异步编程")
        multi = like_rank_multi(["Python", "异步"], "", "Python 异步编程")
        assert multi < single  # 两词命中比一词命中更相关

    def test_position_weight(self):
        early = like_rank_multi(["学习"], "", "我学习异步编程")
        late = like_rank_multi(["学习"], "", "异步编程我学习")
        assert early < late

    def test_single_token_matches_legacy(self):
        """单 token 时与旧 like_rank 语义完全一致。"""
        assert like_rank_multi(["异步"], "异步编程入门", "无相关内容") == \
            like_rank("异步", "异步编程入门", "无相关内容")
        assert like_rank_multi(["PYTHON"], "Python 编程", "c") == \
            like_rank("python", "Python 编程", "c")

    def test_no_match_returns_zero(self):
        assert like_rank_multi(["zzz"], "标题", "内容") == 0.0

    def test_empty_tokens(self):
        assert like_rank_multi([], "标题", "内容") == 0.0
