"""事实核查来源映射与措辞收敛测试。"""

from core_logic import (
    _build_fact_check_fallback_markdown,
    _build_heuristic_claim_items,
    _enrich_fact_check_items_with_claim_sources,
    _find_authoritative_sources,
    decide_video_fact_check_plan,
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


def test_build_fact_check_fallback_markdown_keeps_more_detail() -> None:
    """兜底核查结果也应保留待补充核查点和多个来源，避免内容过于单薄。"""

    fallback = _build_fact_check_fallback_markdown(
        claim_sources=[
            {
                "claim": "台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市。",
                "queries": ["台湾股市 4.47万亿美元 加拿大 第六大股市"],
                "search_markdown": (
                    "- [台湾证券交易所](https://www.twse.com.tw/en/)\n"
                    "- [彭博社](https://www.bloomberg.com/)\n"
                    "- [路透社](https://www.reuters.com/)\n"
                    "- [美丽岛电子报](https://www.my-formosa.com/)"
                ),
            }
        ]
    )

    assert "### 条目1" in fallback
    assert "待补充核查点" in fallback
    assert "https://www.twse.com.tw/en/" in fallback
    assert "https://www.bloomberg.com/" in fallback


def test_build_heuristic_claim_items_prefers_specific_summary_claims() -> None:
    """当模型抽取声明失败时，应尽量从总结要点里提取具体声明而不是退回泛化模板。"""

    summary_md = (
        "## 核心主题\n"
        "- 美国政府高级官员称，目前美国境内有超过10万名非法滞留的中国公民。\n"
        "## 主要内容\n"
        "- 报道提到美国政府正加强对非法移民与签证逾期滞留问题的执法。\n"
        "- 视频还提到部分案件与人口走线网络有关。\n"
    )

    claims = _build_heuristic_claim_items(
        text=summary_md,
        summary_markdown=summary_md,
        max_claims=3,
    )

    assert claims
    assert "超过10万名非法滞留的中国公民" in claims[0]["claim"]


def test_decide_video_fact_check_plan_skips_explicit_test_transcript() -> None:
    """明显的测试/链路字幕仍应直接跳过，避免误触发新闻核查。"""

    transcript = (
        "这是一次产品主路径的模拟测试，用于回归验证 Chrome 插件到 Render 主站的自动开始总结链路。"
        "本次只检查 bridge payload 和 transcript 回传是否正常。"
    )
    summary_md = (
        "## 核心主题\n"
        "- 该视频用于测试插件与主站联动，不属于真实新闻内容。\n"
    )

    plan = decide_video_fact_check_plan(transcript, summary_md)

    assert plan["should_fact_check"] is False
    assert plan["recommended_claim_count"] == 0


def test_decide_video_fact_check_plan_defaults_to_basic_fact_check_for_real_video() -> None:
    """真实视频即使新闻关键词不强，也不应轻易被误判为 skipped。"""

    transcript = (
        "视频围绕一家机构最近公布的多项说法展开，主持人反复提到 2026 年、3 个时间点和两组数字，"
        "还比较了不同口径之间的差异。随后又讨论相关部门、企业和公开表态之间是否一致，"
        "并逐条解释这些数字为什么会影响外界判断。"
    )
    summary_md = (
        "## 核心主题\n"
        "- 视频围绕现实中的机构说法、数字变化和时间线展开梳理。\n\n"
        "## 主要内容\n"
        "- 主讲人整理了多组数字口径，并比较不同来源之间是否一致。\n"
        "- 内容涉及公开表态、时间节点和可交叉验证的具体说法。\n"
        "- 虽然没有明显新闻播报措辞，但整体仍属于适合进一步核查的真实视频内容。\n"
    )

    plan = decide_video_fact_check_plan(transcript, summary_md)

    assert plan["should_fact_check"] is True
    assert plan["recommended_claim_count"] == 3
