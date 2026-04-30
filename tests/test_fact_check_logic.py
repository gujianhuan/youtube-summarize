"""事实核查来源映射与措辞收敛测试。"""

from core_logic import (
    _enrich_fact_check_items_with_claim_sources,
    _find_authoritative_sources,
)


def test_find_authoritative_sources_includes_bloomberg_twse_and_my_formosa() -> None:
    """应能识别新增的主流财经媒体与台湾站点。"""

    text = "彭博社报道台湾股市总市值达4.47万亿美元，美丽岛电子报也有相关评论。"

    sources = _find_authoritative_sources(text)
    urls = {str(item.get("url") or "") for item in sources}

    assert "https://www.bloomberg.com/" in urls
    assert "https://www.twse.com.tw/en/" in urls
    assert "https://www.my-formosa.com/" in urls


def test_enrich_fact_check_softens_absolute_negative_wording_when_sources_exist() -> None:
    """已有候选来源链接时，不应继续保留“未发现任何报道”类绝对否定表述。"""

    fact_md = (
        "### 条目1\n"
        "- 新闻/声明：布伦特原油价格达到120美元。\n"
        "- 核查结论：缺乏证据\n"
        "- 依据：未发现任何主流财经新闻媒体（如路透社、彭博社）在2026年4月报道布伦特原油价格达到120美元。\n"
    )
    claim_sources = [
        {
            "claim": "布伦特原油价格达到120美元",
            "search_markdown": (
                "- [路透社](https://www.reuters.com/)\n"
                "- [彭博社](https://www.bloomberg.com/)"
            ),
        }
    ]

    enriched = _enrich_fact_check_items_with_claim_sources(fact_md, claim_sources)

    assert "未发现任何主流财经新闻媒体" not in enriched
    assert "https://www.reuters.com/" in enriched
    assert "https://www.bloomberg.com/" in enriched
