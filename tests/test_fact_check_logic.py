"""事实核查来源映射与措辞收敛测试。"""

from core_logic import (
    _build_fact_check_fallback_markdown,
    _build_heuristic_claim_items,
    _decode_google_news_url,
    _dedupe_fact_check_source_links,
    _ensure_fact_check_item_coverage,
    _enrich_fact_check_items_with_claim_sources,
    _extract_fact_check_source_links,
    _fetch_bing_web_results,
    _fetch_google_news_results,
    _find_authoritative_sources,
    _normalize_fact_check_claim,
    _normalize_fact_check_conclusions_with_sources,
    _prepare_fact_check_queries,
    _recover_reuters_direct_article_hit,
    _recover_syndicated_fact_check_hit,
    _select_fact_check_queries,
    _unwrap_bing_news_redirect,
    decide_video_fact_check_plan,
    perform_web_search,
)


def test_find_authoritative_sources_includes_bloomberg_twse_and_my_formosa() -> None:
    """应能识别新增的主流财经媒体与台湾站点。"""

    text = "彭博社报道台湾股市总市值达4.47万亿美元，美丽岛电子报也有相关评论。"

    sources = _find_authoritative_sources(text)
    urls = {str(item.get("url") or "") for item in sources}

    assert "https://www.bloomberg.com/" in urls
    assert "https://www.twse.com.tw/en/" in urls
    assert "https://www.my-formosa.com/" in urls


def test_find_authoritative_sources_includes_ap_nyt_wapo_and_kyiv_city() -> None:
    """应补充常见国际新闻与政府来源，提升国际事件检索命中率。"""

    text = "基辅市政府、Associated Press、New York Times 与 Washington Post 都提到了相关事件。"

    sources = _find_authoritative_sources(text)
    urls = {str(item.get("url") or "") for item in sources}

    assert "https://kyivcity.gov.ua/" in urls
    assert "https://apnews.com/" in urls
    assert "https://www.nytimes.com/" in urls
    assert "https://www.washingtonpost.com/" in urls


def test_find_authoritative_sources_includes_wsj_and_ft() -> None:
    """主流国际财经媒体提及时，应识别 WSJ 与 FT。"""

    text = "华尔街日报和 Financial Times 都提到这笔香港IPO的国际配售情况。"

    sources = _find_authoritative_sources(text)
    urls = {str(item.get("url") or "") for item in sources}

    assert "https://www.wsj.com/" in urls
    assert "https://www.ft.com/" in urls


def test_find_authoritative_sources_includes_macro_and_central_bank_sources() -> None:
    """宏观数据与央行类说法应能映射到外文官方数据源。"""

    text = "未来一周关注美国PCE、加拿大GDP、欧元区通胀、日本工业生产、新西兰央行利率会议与中国PMI。"

    sources = _find_authoritative_sources(text)
    urls = {str(item.get("url") or "") for item in sources}

    assert "https://www.bea.gov/" in urls
    assert "https://www.statcan.gc.ca/en/start" in urls
    assert "https://ec.europa.eu/eurostat" in urls
    assert "https://www.meti.go.jp/english/" in urls
    assert "https://www.rbnz.govt.nz/" in urls
    assert "https://www.stats.gov.cn/" in urls


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


def test_dedupe_fact_check_source_links_normalizes_trailing_slashes() -> None:
    """同一来源即使 URL 末尾斜杠不同，也应去重。"""

    deduped = _dedupe_fact_check_source_links(
        [
            ("路透社", "https://www.reuters.com/"),
            ("Reuters", "https://www.reuters.com"),
            ("彭博社 Markets", "https://www.bloomberg.com/markets/"),
            ("Bloomberg Markets", "https://www.bloomberg.com/markets"),
        ]
    )

    assert deduped == [
        ("路透社", "https://www.reuters.com/"),
        ("彭博社 Markets", "https://www.bloomberg.com/markets/"),
    ]


def test_dedupe_fact_check_source_links_ignores_tracking_query_params() -> None:
    """同一来源只有追踪参数不同，也应视为重复。"""

    deduped = _dedupe_fact_check_source_links(
        [
            ("Reuters A", "https://www.reuters.com/world/example?utm_source=youtube"),
            ("Reuters B", "https://www.reuters.com/world/example?utm_medium=social"),
            ("Reuters C", "https://www.reuters.com/world/example"),
        ]
    )

    assert deduped == [
        ("Reuters A", "https://www.reuters.com/world/example?utm_source=youtube"),
    ]


def test_enrich_fact_check_dedupes_repeated_links_from_search_markdown() -> None:
    """搜索上下文重复给出同一来源时，最终来源列表不应重复展示。"""

    fact_md = (
        "### 条目1\n"
        "- 新闻/声明：台湾股市总市值达到4.47万亿美元。\n"
        "- 核查结论：缺乏证据\n"
        "- 判断依据：现有候选来源不足以直接支撑该说法。\n"
    )
    claim_sources = [
        {
            "claim": "台湾股市总市值达到4.47万亿美元",
            "search_markdown": (
                "- [路透社](https://www.reuters.com/)\n"
                "- [路透社](https://www.reuters.com)\n"
                "- [台湾证券交易所](https://www.twse.com.tw/en/)\n"
            ),
        }
    ]

    enriched = _enrich_fact_check_items_with_claim_sources(fact_md, claim_sources)

    assert enriched.count("https://www.reuters.com/") == 1
    assert "https://www.twse.com.tw/en/" in enriched


def test_extract_fact_check_source_links_filters_out_search_engine_pages() -> None:
    """来源列表应只保留实际报道/官网，不应混入 Google/Bing 搜索页。"""

    links = _extract_fact_check_source_links(
        "### 搜索关键字: 台湾股市 4.47万亿美元\n"
        "- [Google 新闻核查](https://www.google.com/search?q=test&tbm=nws)\n"
        "- [Bing 新闻核查](https://www.bing.com/news/search?q=test)\n"
        "- 命中的候选报道：\n"
        "  - [Reuters story](https://www.reuters.com/world/example)\n"
        "- 权威站点参考：\n"
        "  - [台湾证券交易所](https://www.twse.com.tw/en/)\n"
        "  - [台湾证券交易所 定向搜索](https://www.google.com/search?q=site%3Atwse.com.tw)\n"
    )

    assert ("Reuters story", "https://www.reuters.com/world/example") in links
    assert ("台湾证券交易所", "https://www.twse.com.tw/en/") in links
    assert all("google." not in url.lower() for _, url in links)
    assert all("bing." not in url.lower() for _, url in links)


def test_perform_web_search_includes_candidate_news_hits(monkeypatch) -> None:
    """检索结果应包含命中的候选报道标题，而不只是搜索入口。"""

    monkeypatch.setattr(
        "core_logic._fetch_bing_news_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "台湾股市市值升至4.47万亿美元",
                "url": "https://example.com/news/tw-market-cap",
                "source": "Reuters",
                "snippet": "报道提到台湾股市总市值达到4.47万亿美元。",
                "published_at": "Fri, 01 May 2026 08:00:00 GMT",
            }
        ],
    )
    monkeypatch.setattr("core_logic._fetch_bing_web_results", lambda query, proxy_url=None, max_items=4: [])

    rendered = perform_web_search(["台湾股市 4.47万亿美元"])

    assert "命中的候选报道" in rendered
    assert "台湾股市市值升至4.47万亿美元" in rendered
    assert "https://example.com/news/tw-market-cap" in rendered
    assert "来源：Reuters" in rendered


def test_perform_web_search_keeps_web_hits_even_when_news_hits_exist(monkeypatch) -> None:
    """即使新闻已命中，也应继续保留对应网页结果，方便先找到相关页面。"""

    monkeypatch.setattr(
        "core_logic._fetch_bing_news_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "Breaking news item",
                "url": "https://example.com/news/item",
                "source": "Reuters",
                "snippet": "News snippet.",
                "published_at": "Fri, 01 May 2026 08:00:00 GMT",
            }
        ],
    )
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic._fetch_bing_web_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "Official statement page",
                "url": "https://www.state.gov/briefing/example",
                "source": "state.gov",
                "snippet": "Official page snippet.",
                "published_at": "",
            }
        ],
    )

    rendered = perform_web_search(["Rubio meeting statement"])

    assert "命中的候选报道" in rendered
    assert "命中的候选网页" in rendered
    assert "https://www.state.gov/briefing/example" in rendered


def test_perform_web_search_recovers_primary_source_from_msn_syndication(monkeypatch) -> None:
    """Reuters on MSN 这类聚合结果应继续追到原始媒体页。"""

    monkeypatch.setattr(
        "core_logic._fetch_bing_news_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "China's Xi may visit North Korea as early as next week, Yonhap reports",
                "url": "https://www.msn.com/en-us/news/world/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports/ar-AA23Il3X",
                "source": "Reuters on MSN",
                "snippet": "SEOUL, May 21 (Reuters) - Chinese President Xi Jinping may visit North Korea as early as next week.",
                "published_at": "Wed, 20 May 2026 23:18:32 GMT",
            }
        ],
    )
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])

    def fake_fetch_bing_web_results(query, proxy_url=None, max_items=4):
        if str(query).startswith("site:www.reuters.com "):
            return [
                {
                    "title": "China's Xi may visit North Korea as early as next week, Yonhap reports",
                    "url": "https://www.reuters.com/world/asia-pacific/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports-2026-05-21/",
                    "source": "Reuters",
                    "snippet": "SEOUL, May 21 (Reuters) - Chinese President Xi Jinping may visit North Korea as early as next week.",
                    "published_at": "",
                }
            ]
        return []

    monkeypatch.setattr("core_logic._fetch_bing_web_results", fake_fetch_bing_web_results)
    monkeypatch.setattr(
        "core_logic.extract_web_article_text",
        lambda url, proxy_url=None: {
            "clean_text": "China's Xi may visit North Korea as early as next week, Yonhap reports. Reuters report from Seoul."
        },
    )

    rendered = perform_web_search(
        ["Xi Jinping may visit North Korea Reuters"],
        claim_text="习近平可能访问朝鲜，影响地缘政治和东亚资本市场",
    )

    assert "https://www.reuters.com/world/asia-pacific/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports-2026-05-21/" in rendered
    assert "https://www.msn.com/en-us/news/world/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports/ar-AA23Il3X" not in rendered
    assert "追源：由 Reuters on MSN 聚合页恢复" in rendered


def test_decode_google_news_url_decodes_batch_execute_response(monkeypatch) -> None:
    """Google News RSS 编码链接应能通过 batchexecute 还原成原始媒体 URL。"""

    class DummyGetResponse:
        status_code = 200
        text = '<c-wiz><div data-n-a-sg="sig-token" data-n-a-ts="1710000000"></div></c-wiz>'
        headers = {}

    class DummyResponse:
        text = ')]}\'\n\n[["wrb.fr","Fbv4je","[\\"garturlres\\",\\"https://www.reuters.com/world/example-story\\",null,null]",null,null]]'

        def raise_for_status(self) -> None:
            return None

    post_calls = []

    def fake_get(*args, **kwargs):
        return DummyGetResponse()

    def fake_post(*args, **kwargs):
        post_calls.append(kwargs)
        return DummyResponse()

    monkeypatch.setattr("core_logic.requests.get", fake_get)
    monkeypatch.setattr("core_logic.requests.post", fake_post)

    decoded = _decode_google_news_url(
        "https://news.google.com/rss/articles/CBMirwFBVV95cUxOcUlqRVQ2eVpsMFJKUFQ1TTZtX3ZPMUs3R3N5R18yZ1pZOENSQ01BdG9TUGlacGtPV3cySDVMS0tCZGVXeWk3SWNmVDZVV3EzQnRMbWNTbUZDbHd4Z2dObG1TRU40bER5V1VwSjBITGVNSnB3bWhacGpIRkNmTGhWcEs4aG9MR3BxMWNHT3NBaGI4LWVGWG5SSzM5Q216YlFTa1E4VzBSaktEdUt0Y05Z?oc=5"
    )

    assert decoded == "https://www.reuters.com/world/example-story"
    assert post_calls
    assert "sig-token" in str(post_calls[0]["data"]["f.req"])
    assert "1710000000" in str(post_calls[0]["data"]["f.req"])


def test_fetch_google_news_results_keeps_source_url_from_feed(monkeypatch) -> None:
    """Google News RSS 项应保留 source 节点自带的媒体主页，供后续追源过滤使用。"""

    class DummyResponse:
        text = (
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<rss><channel><item>"
            "<title>China's Xi may visit North Korea as early as next week, Yonhap reports - Reuters</title>"
            "<link>https://news.google.com/rss/articles/demo?oc=5</link>"
            "<pubDate>Wed, 20 May 2026 23:50:00 GMT</pubDate>"
            "<description>sample</description>"
            '<source url="https://www.reuters.com">Reuters</source>'
            "</item></channel></rss>"
        )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("core_logic.requests.get", lambda *args, **kwargs: DummyResponse())
    monkeypatch.setattr("core_logic._decode_google_news_url", lambda url, proxy_url=None: url)

    items = _fetch_google_news_results("Xi Jinping may visit North Korea Reuters")

    assert items
    assert items[0]["source"] == "Reuters"
    assert items[0]["source_url"] == "https://www.reuters.com"


def test_recover_syndicated_fact_check_hit_uses_google_news_title_for_exact_site_search(monkeypatch) -> None:
    """Google News 只给聚合链接时，应继续用精确标题做一次 site: 追源，尽量落回原媒体直链。"""

    search_queries = []
    direct_url = "https://www.reuters.com/world/asia-pacific/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports-2026-05-21/"

    def fake_fetch_bing_web_results(query, proxy_url=None, max_items=4):
        search_queries.append(query)
        if query.startswith('site:www.reuters.com "China\'s Xi may visit North Korea as early as next week, Yonhap reports"'):
            return [
                {
                    "title": "China's Xi may visit North Korea as early as next week, Yonhap reports",
                    "url": direct_url,
                    "source": "Reuters",
                    "snippet": "Reuters report from Seoul.",
                    "published_at": "",
                }
            ]
        return []

    monkeypatch.setattr("core_logic._fetch_bing_web_results", fake_fetch_bing_web_results)
    monkeypatch.setattr(
        "core_logic._fetch_google_news_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "China's Xi may visit North Korea as early as next week, Yonhap reports - Reuters",
                "url": "https://news.google.com/rss/articles/demo?oc=5",
                "source": "Reuters",
                "source_url": "https://www.reuters.com",
                "snippet": "Reuters",
                "published_at": "Wed, 20 May 2026 23:50:00 GMT",
            }
        ],
    )
    monkeypatch.setattr(
        "core_logic.extract_web_article_text",
        lambda url, proxy_url=None: {
            "clean_text": "China's Xi may visit North Korea as early as next week, Yonhap reports. Reuters report from Seoul."
        },
    )

    recovered = _recover_syndicated_fact_check_hit(
        {
            "title": "China's Xi may visit North Korea as early as next week, Yonhap reports",
            "url": "https://www.msn.com/en-us/news/world/chinas-xi-may-visit-north-korea/as-AA23Il3X",
            "source": "Reuters on MSN",
            "snippet": "MSN syndicated copy.",
            "published_at": "",
        },
        claim_text="习近平可能访问朝鲜，影响地缘政治和东亚资本市场",
        query_text="Xi Jinping may visit North Korea Reuters",
    )

    assert recovered is not None
    assert recovered["url"] == direct_url
    assert any(
        query.startswith('site:www.reuters.com "China\'s Xi may visit North Korea as early as next week, Yonhap reports"')
        for query in search_queries
    )


def test_recover_syndicated_fact_check_hit_guesses_reuters_direct_url_from_reposted_story(monkeypatch) -> None:
    """即使不是 MSN，只要转载页明确标出 Reuters，也应尝试直接恢复 Reuters 原文链接。"""

    direct_url = "https://www.reuters.com/world/asia-pacific/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports-2026-05-20/"
    fetched_urls = []

    def fake_extract(url, proxy_url=None):
        fetched_urls.append(url)
        if url == direct_url:
            return {
                "clean_text": (
                    "China's Xi may visit North Korea as early as next week, Yonhap reports. "
                    "SEOUL, May 21 (Reuters) - Chinese President Xi Jinping may visit North Korea as early as next week."
                )
            }
        raise RuntimeError("not found")

    monkeypatch.setattr("core_logic.extract_web_article_text", fake_extract)

    recovered = _recover_syndicated_fact_check_hit(
        {
            "title": "China's Xi may visit North Korea as early as next week, Yonhap reports",
            "url": "https://www.usnews.com/news/world/articles/2026-05-20/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports",
            "source": "U.S. News & World Report",
            "snippet": "SEOUL, May 21 (Reuters) - Chinese President Xi Jinping may visit North Korea as early as next week.",
            "published_at": "Wed, 20 May 2026 17:03:00 GMT",
        },
        claim_text="习近平可能访问朝鲜，影响地缘政治和东亚资本市场",
        query_text="Xi Jinping may visit North Korea Reuters",
    )

    assert recovered is not None
    assert recovered["url"] == direct_url
    assert recovered["source"] == "Reuters"
    assert direct_url in fetched_urls


def test_recover_reuters_direct_article_hit_falls_back_to_page_metadata(monkeypatch) -> None:
    """正文提取失败时，若页面标题与 canonical 仍明显对应 Reuters 原文，也应继续恢复。"""

    direct_url = "https://www.reuters.com/world/asia-pacific/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports-2026-05-21/"

    class DummyResponse:
        status_code = 200
        text = (
            "<html><head>"
            "<title>China's Xi may visit North Korea as early as next week, Yonhap reports | Reuters</title>"
            '<meta property="og:title" content="China\'s Xi may visit North Korea as early as next week, Yonhap reports - Reuters"/>'
            f'<link rel="canonical" href="{direct_url}"/>'
            "</head><body>metadata only</body></html>"
        )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        "core_logic.extract_web_article_text",
        lambda url, proxy_url=None: (_ for _ in ()).throw(RuntimeError("blocked")),
    )
    monkeypatch.setattr("core_logic.requests.get", lambda *args, **kwargs: DummyResponse())

    recovered = _recover_reuters_direct_article_hit(
        title="China's Xi may visit North Korea as early as next week, Yonhap reports",
        published_at="Wed, 20 May 2026 23:18:32 GMT",
        claim_text="习近平可能访问朝鲜，影响地缘政治和东亚资本市场",
        query_text="Xi Jinping may visit North Korea Reuters",
        snippet="SEOUL, May 21 (Reuters) - Chinese President Xi Jinping may visit North Korea as early as next week.",
    )

    assert recovered is not None
    assert recovered["url"] == direct_url
    assert recovered["source"] == "Reuters"


def test_recover_reuters_direct_article_hit_rejects_non_article_canonical_page(monkeypatch) -> None:
    """若 canonical 指向 Reuters 直播/专题页，则不能把它当作原始报道恢复。"""

    live_url = "https://www.reuters.com/world/live-updates/trump-xi-diplomacy-2026-05-21/"

    class DummyResponse:
        status_code = 200
        text = (
            "<html><head>"
            "<title>China's Xi may visit North Korea as early as next week, Yonhap reports | Reuters</title>"
            '<meta property="og:title" content="China\'s Xi may visit North Korea as early as next week, Yonhap reports - Reuters"/>'
            f'<link rel="canonical" href="{live_url}"/>'
            "</head><body>metadata only</body></html>"
        )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr(
        "core_logic.extract_web_article_text",
        lambda url, proxy_url=None: (_ for _ in ()).throw(RuntimeError("blocked")),
    )
    monkeypatch.setattr("core_logic.requests.get", lambda *args, **kwargs: DummyResponse())

    recovered = _recover_reuters_direct_article_hit(
        title="China's Xi may visit North Korea as early as next week, Yonhap reports",
        published_at="Wed, 20 May 2026 23:18:32 GMT",
        claim_text="习近平可能访问朝鲜，影响地缘政治和东亚资本市场",
        query_text="Xi Jinping may visit North Korea Reuters",
        snippet="SEOUL, May 21 (Reuters) - Chinese President Xi Jinping may visit North Korea as early as next week.",
    )

    assert recovered is None


def test_recover_reuters_direct_article_hit_falls_back_to_slug_guess_when_fetch_blocked(monkeypatch) -> None:
    """若 Reuters 转载线索足够强，即使正文和元数据都抓不到，也应保留高置信度直链推测。"""

    direct_url = "https://www.reuters.com/world/asia-pacific/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports-2026-05-21/"

    monkeypatch.setattr(
        "core_logic.extract_web_article_text",
        lambda url, proxy_url=None: (_ for _ in ()).throw(RuntimeError("blocked")),
    )
    monkeypatch.setattr(
        "core_logic._fetch_fact_check_page_metadata",
        lambda url, proxy_url=None: {},
    )

    recovered = _recover_reuters_direct_article_hit(
        title="China's Xi may visit North Korea as early as next week, Yonhap reports",
        published_at="Wed, 20 May 2026 23:18:32 GMT",
        claim_text="习近平可能访问朝鲜，影响地缘政治和东亚资本市场",
        query_text="Xi Jinping may visit North Korea Reuters",
        snippet="SEOUL, May 21 (Reuters) - Chinese President Xi Jinping may visit North Korea as early as next week.",
    )

    assert recovered is not None
    assert recovered["url"] == direct_url
    assert recovered["source"] == "Reuters"
    assert recovered["recovery_method"] == "slug_guess"


def test_recover_reuters_direct_article_hit_tries_query_driven_title_variant(monkeypatch) -> None:
    """若转载标题比 Reuters 原题更短，也应尝试结合查询线索补出常见 Reuters 从句。"""

    direct_url = "https://www.reuters.com/world/europe/rubio-says-us-will-stop-mediating-ukraine-peace-talks-if-no-progress-2026-04-18/"

    def fake_extract(url, proxy_url=None):
        if url == direct_url:
            return {
                "clean_text": (
                    "Rubio says U.S. will stop mediating Ukraine peace talks if no progress. "
                    "Reuters report on Ukraine talks."
                )
            }
        raise RuntimeError("not found")

    monkeypatch.setattr("core_logic.extract_web_article_text", fake_extract)

    recovered = _recover_reuters_direct_article_hit(
        title="Rubio says U.S. will stop mediating Ukraine peace talks",
        published_at="Fri, 18 Apr 2026 11:03:00 GMT",
        claim_text="美国国务卿卢比奥宣布美国退出乌克兰战争调解，称谈判无成果",
        query_text="Rubio Ukraine talks no progress Reuters",
        snippet="Reuters report on Ukraine talks.",
    )

    assert recovered is not None
    assert recovered["url"] == direct_url
    assert recovered["source"] == "Reuters"


def test_recover_syndicated_fact_check_hit_tries_exact_title_site_query_without_google(monkeypatch) -> None:
    """没有 Google News 辅助时，也应先用精确标题 site 查询追源。"""

    search_queries = []
    direct_url = "https://www.reuters.com/world/europe/rubio-says-us-will-stop-mediating-ukraine-peace-talks-if-no-progress-2026-04-18/"

    def fake_fetch_bing_web_results(query, proxy_url=None, max_items=4):
        search_queries.append(query)
        if query == 'site:www.reuters.com "Rubio says U.S. will stop mediating Ukraine peace talks"':
            return [
                {
                    "title": "Rubio says U.S. will stop mediating Ukraine peace talks if no progress",
                    "url": direct_url,
                    "source": "Reuters",
                    "snippet": "Reuters report on Ukraine talks.",
                    "published_at": "",
                }
            ]
        return []

    monkeypatch.setattr("core_logic._fetch_bing_web_results", fake_fetch_bing_web_results)
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic.extract_web_article_text",
        lambda url, proxy_url=None: {
            "clean_text": "Rubio says U.S. will stop mediating Ukraine peace talks if no progress, Reuters reported."
        },
    )

    recovered = _recover_syndicated_fact_check_hit(
        {
            "title": "Rubio says U.S. will stop mediating Ukraine peace talks",
            "url": "https://www.msn.com/en-us/news/world/rubio-says-us-will-stop-mediating-ukraine-peace-talks/ar-AA24demo",
            "source": "Reuters on MSN",
            "snippet": "Syndicated Reuters copy.",
            "published_at": "Fri, 18 Apr 2026 11:03:00 GMT",
        },
        claim_text="美国国务卿卢比奥宣布美国退出乌克兰战争调解，称谈判无成果",
        query_text="Rubio Ukraine talks no progress Reuters",
    )

    assert recovered is not None
    assert recovered["url"] == direct_url
    assert search_queries[0] == 'site:www.reuters.com "Rubio says U.S. will stop mediating Ukraine peace talks"'


def test_recover_syndicated_fact_check_hit_recovers_from_google_news_aggregator(monkeypatch) -> None:
    """Google News 聚合链接即使带 source_url，也应继续追到原始 Reuters 直链。"""

    direct_url = "https://www.reuters.com/world/asia-pacific/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports-2026-05-21/"

    def fake_extract(url, proxy_url=None):
        if url == direct_url:
            return {
                "clean_text": (
                    "China's Xi may visit North Korea as early as next week, Yonhap reports. "
                    "SEOUL, May 21 (Reuters) - Chinese President Xi Jinping may visit North Korea as early as next week."
                )
            }
        raise RuntimeError("not found")

    monkeypatch.setattr("core_logic.extract_web_article_text", fake_extract)

    recovered = _recover_syndicated_fact_check_hit(
        {
            "title": "China's Xi may visit North Korea as early as next week, Yonhap reports - Reuters",
            "url": "https://news.google.com/rss/articles/demo?oc=5",
            "source": "Reuters",
            "source_url": "https://www.reuters.com",
            "snippet": "Reuters",
            "published_at": "Wed, 20 May 2026 23:50:00 GMT",
        },
        claim_text="习近平可能访问朝鲜，影响地缘政治和东亚资本市场",
        query_text="Xi Jinping may visit North Korea Reuters",
    )

    assert recovered is not None
    assert recovered["url"] == direct_url
    assert recovered["source"] == "Reuters"


def test_fetch_bing_web_results_filters_off_domain_hits_for_site_query(monkeypatch) -> None:
    """site: 查询抓回的网页结果必须真的命中目标域名，不能混入异站噪声。"""

    class DummyResponse:
        text = (
            "<html><body>"
            '<li class="b_algo"><h2><a href="https://apps.microsoft.com/detail/example">U 校园</a></h2>'
            '<div class="b_caption"><p>noise</p></div><cite>apps.microsoft.com</cite></li>'
            '<li class="b_algo"><h2><a href="https://www.reuters.com/world/example-story/">Reuters story</a></h2>'
            '<div class="b_caption"><p>Reuters report.</p></div><cite>www.reuters.com</cite></li>'
            "</body></html>"
        )

        def raise_for_status(self) -> None:
            return None

    monkeypatch.setattr("core_logic.requests.get", lambda *args, **kwargs: DummyResponse())

    items = _fetch_bing_web_results('site:www.reuters.com "Rubio says U.S. will stop mediating Ukraine peace talks"')

    assert len(items) == 1
    assert items[0]["url"] == "https://www.reuters.com/world/example-story/"


def test_perform_web_search_uses_google_news_for_authoritative_site_query(monkeypatch) -> None:
    """权威站点的 site: 查询若 Bing 空白，应继续用 Google News 聚合结果恢复原文。"""

    direct_url = "https://www.reuters.com/world/asia-pacific/chinas-xi-may-visit-north-korea-as-early-as-next-week-yonhap-reports-2026-05-21/"

    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_bing_web_results", lambda query, proxy_url=None, max_items=4: [])

    def fake_google_news(query, proxy_url=None, max_items=4):
        if str(query).startswith("site:www.reuters.com "):
            return [
                {
                    "title": "China's Xi may visit North Korea as early as next week, Yonhap reports - Reuters",
                    "url": "https://news.google.com/rss/articles/demo?oc=5",
                    "source": "Reuters",
                    "source_url": "https://www.reuters.com",
                    "snippet": "Reuters",
                    "published_at": "Wed, 20 May 2026 23:50:00 GMT",
                }
            ]
        return []

    def fake_extract(url, proxy_url=None):
        if url == direct_url:
            return {
                "clean_text": (
                    "China's Xi may visit North Korea as early as next week, Yonhap reports. "
                    "SEOUL, May 21 (Reuters) - Chinese President Xi Jinping may visit North Korea as early as next week."
                )
            }
        raise RuntimeError("not found")

    monkeypatch.setattr("core_logic._fetch_google_news_results", fake_google_news)
    monkeypatch.setattr("core_logic.extract_web_article_text", fake_extract)

    rendered = perform_web_search(
        ["site:www.reuters.com Xi Jinping may visit North Korea Reuters"],
        claim_text="习近平可能访问朝鲜，影响地缘政治和东亚资本市场",
    )

    assert direct_url in rendered
    assert "追源：由 Reuters 聚合页恢复" in rendered


def test_perform_web_search_filters_noisy_pages_from_web_hits(monkeypatch) -> None:
    """来源发现应过滤视频页、登录页和专题页等噪声结果。"""

    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic._fetch_bing_web_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "Watch video: event recap",
                "url": "https://www.youtube.com/watch?v=demo",
                "source": "YouTube",
                "snippet": "Video page",
                "published_at": "",
            },
            {
                "title": "Login - Example",
                "url": "https://example.com/login",
                "source": "example.com",
                "snippet": "Please sign in",
                "published_at": "",
            },
            {
                "title": "Reuters reports new policy move",
                "url": "https://www.reuters.com/world/example-policy",
                "source": "Reuters",
                "snippet": "Reuters reported the policy move after the meeting.",
                "published_at": "",
            },
        ],
    )

    rendered = perform_web_search(["policy meeting statement"], claim_text="policy meeting statement")

    assert "https://www.reuters.com/world/example-policy" in rendered
    assert "youtube.com/watch" not in rendered
    assert "https://example.com/login" not in rendered


def test_perform_web_search_drops_irrelevant_web_hit_with_low_query_overlap(monkeypatch) -> None:
    """标题摘要都对不上查询核心词的网页，不应作为候选来源展示。"""

    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic._fetch_bing_web_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "U 校园 - Windows官方下载 | 微软应用商店 | Microsoft Store",
                "url": "https://apps.microsoft.com/detail/xp9mk65wjlsm1m?hl=zh-cn&gl=CN",
                "source": "https://apps.microsoft.com › detail",
                "snippet": "U校园智慧教学云平台，为高等院校外语教学提供教、学、评、测、研一站式方案。",
                "published_at": "",
            }
        ],
    )

    rendered = perform_web_search(
        ["Rubio says U.S. will stop mediating Ukraine peace talks"],
        claim_text="美国国务卿卢比奥宣布美国退出乌克兰战争调解，称谈判无成果",
    )

    assert "apps.microsoft.com/detail/xp9mk65wjlsm1m" not in rendered
    assert "自动检索结果：当前未抓到可直接引用的候选网页或报道。" in rendered


def test_perform_web_search_drops_reference_profile_page_for_event_claim(monkeypatch) -> None:
    """事件型声明不应把人物百科/简介页当成候选来源。"""

    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic._fetch_bing_web_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "Marco Rubio | Education, Trump, Nationality, & Facts - Britannica",
                "url": "https://www.britannica.com/biography/Marco-Rubio",
                "source": "Britannica",
                "snippet": "Marco Rubio is an American Republican politician and the 72nd U.S. Secretary of State.",
                "published_at": "",
            }
        ],
    )

    rendered = perform_web_search(
        ["Rubio says U.S. will stop mediating Ukraine peace talks"],
        claim_text="美国国务卿卢比奥宣布美国退出乌克兰战争调解，称谈判无成果",
    )

    assert "britannica.com/biography/Marco-Rubio" not in rendered
    assert "自动检索结果：当前未抓到可直接引用的候选网页或报道。" in rendered


def test_perform_web_search_prioritizes_authoritative_source_pages(monkeypatch) -> None:
    """同批候选网页里，应优先把更像原始出处的官网页排在前面。"""

    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic._fetch_bing_web_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "Roundup blog about the meeting",
                "url": "https://randomblog.example.com/topic/meeting-roundup",
                "source": "randomblog.example.com",
                "snippet": "A generic roundup page.",
                "published_at": "",
            },
            {
                "title": "Official statement page",
                "url": "https://www.state.gov/briefing/example",
                "source": "state.gov",
                "snippet": "The department published an official statement after the meeting.",
                "published_at": "",
            },
        ],
    )

    rendered = perform_web_search(["meeting statement"], claim_text="美国国务院 meeting statement")

    assert "https://www.state.gov/briefing/example" in rendered
    assert "randomblog.example.com/topic/meeting-roundup" not in rendered


def test_perform_web_search_uses_article_body_match_to_filter_weak_pages(monkeypatch) -> None:
    """正文高匹配的出处页应被保留，正文几乎不相关的弱候选页应被压掉。"""

    monkeypatch.setattr("core_logic._find_authoritative_sources", lambda text: [])
    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic._fetch_bing_web_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "Diplomacy recap",
                "url": "https://example.com/analysis/diplomacy-recap",
                "source": "example.com",
                "snippet": "A generic recap of regional diplomacy.",
                "published_at": "",
            },
            {
                "title": "Press briefing transcript",
                "url": "https://www.state.gov/briefing/example",
                "source": "state.gov",
                "snippet": "Transcript of the briefing after the meeting.",
                "published_at": "",
            },
        ],
    )

    def fake_extract_web_article_text(url, proxy_url=None):
        if "state.gov" in url:
            return {
                "clean_text": (
                    "Secretary Rubio met Wang Yi in Kuala Lumpur on 2026-05-24. "
                    "The State Department then published the full briefing transcript."
                )
            }
        return {
            "clean_text": "This page is a broad recap about diplomacy and regional trends."
        }

    monkeypatch.setattr("core_logic.extract_web_article_text", fake_extract_web_article_text)

    rendered = perform_web_search(
        ["Rubio Wang Yi Kuala Lumpur 2026-05-24 statement"],
        claim_text="Rubio Wang Yi Kuala Lumpur 2026-05-24 statement",
    )

    assert "https://www.state.gov/briefing/example" in rendered
    assert "https://example.com/analysis/diplomacy-recap" not in rendered
    assert "正文匹配：" in rendered


def test_parse_fact_check_section_collects_multiline_source_block_without_leaking_into_body() -> None:
    """来源字段后的多行链接应全部归入来源，而不是同时落进正文。"""

    from app import _parse_fact_check_section

    parsed = _parse_fact_check_section(
        "### 条目1\n"
        "- 新闻/声明：测试声明\n"
        "- 核查结论：存疑\n"
        "- 来源/出处：\n"
        "  - [Reuters](https://www.reuters.com/world/example)\n"
        "  - [AP](https://apnews.com/example)\n"
    )

    body_markdown = str(parsed.get("body_markdown") or "")
    source_links = list(parsed.get("source_links") or [])

    assert "https://www.reuters.com/world/example" not in body_markdown
    assert "https://apnews.com/example" not in body_markdown
    assert ("Reuters", "https://www.reuters.com/world/example") in source_links
    assert ("AP", "https://apnews.com/example") in source_links


def test_perform_web_search_explains_zero_hits_without_overclaiming(monkeypatch) -> None:
    """自动检索没抓到结果时，应说明是未命中，而不是暗示全网不存在报道。"""

    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_bing_web_results", lambda query, proxy_url=None, max_items=4: [])

    rendered = perform_web_search(["卢比奥 退出 调解 俄乌 冲突"])

    assert "当前未抓到可直接引用的候选网页或报道" in rendered
    assert "这不等于“全网不存在相关内容”" in rendered


def test_perform_web_search_falls_back_to_google_news_hits(monkeypatch) -> None:
    """Bing 没命中时，应继续吸收 Google News RSS 的候选结果。"""

    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_bing_web_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic._fetch_google_news_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "Xi may visit North Korea next week",
                "url": "https://example.com/news/xi-nk",
                "source": "Bloomberg",
                "snippet": "Yonhap reported Xi could travel to Pyongyang next week.",
                "published_at": "Thu, 21 May 2026 10:00:00 GMT",
            }
        ],
    )

    rendered = perform_web_search(["Xi visit North Korea next week"])

    assert "命中的候选报道" in rendered
    assert "Xi may visit North Korea next week" in rendered
    assert "https://example.com/news/xi-nk" in rendered
    assert "来源：Bloomberg" in rendered


def test_perform_web_search_falls_back_to_bing_web_hits_when_news_misses(monkeypatch) -> None:
    """新闻 RSS 没命中时，仍应继续吸收普通网页搜索结果。"""

    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic._fetch_bing_web_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "Official statement on the meeting",
                "url": "https://www.state.gov/briefing/example",
                "source": "state.gov",
                "snippet": "The department published an official statement after the meeting.",
                "published_at": "",
            }
        ],
    )

    rendered = perform_web_search(["Rubio meeting statement"])

    assert "命中的候选网页" in rendered
    assert "https://www.state.gov/briefing/example" in rendered
    assert "来源：state.gov" in rendered


def test_unwrap_bing_news_redirect_returns_target_url() -> None:
    """Bing RSS 点击跳转链接应尽量还原为原始新闻地址。"""

    wrapped = (
        "https://www.bing.com/news/apiclick.aspx?"
        "ref=FexRss&url=https%3A%2F%2Fexample.com%2Fstory%3Fa%3D1"
    )

    assert _unwrap_bing_news_redirect(wrapped) == "https://example.com/story?a=1"


def test_prepare_fact_check_queries_adds_relaxed_version_without_exact_date() -> None:
    """日期过窄时，应自动补一个更宽松的检索词。"""

    queries = _prepare_fact_check_queries(
        "川普在2026年5月24日前后发表上述言论",
        ["川普 2026年5月24日前后 发表上述言论"],
    )

    assert any("2026年5月24日前后" in item for item in queries)
    assert any("川普" in item and "发表" in item and "2026年5月24日前后" not in item for item in queries)


def test_prepare_fact_check_queries_adds_english_official_queries_for_rbnz_topic() -> None:
    """中文央行说法应补充外文官方检索词与定向站点查询。"""

    queries = _prepare_fact_check_queries(
        "新西兰央行可能维持利率不变，但前瞻指引或警告未来加息",
        ["新西兰央行 维持利率不变 警告未来加息"],
    )

    assert any("RBNZ official cash rate" in item for item in queries)
    assert any("RBNZ monetary policy statement" in item for item in queries)
    assert any(item.startswith("site:www.rbnz.govt.nz ") for item in queries)


def test_prepare_fact_check_queries_adds_event_level_english_queries_for_geopolitical_topic() -> None:
    """复杂地缘政治说法应补成更像新闻标题的英文检索词。"""

    queries = _prepare_fact_check_queries(
        "美国国务卿卢比奥宣布美国退出乌克兰战争调解，称谈判无成果",
        ["美国国务卿卢比奥宣布美国退出乌克兰战争调解，称谈判无成果"],
    )

    assert any("Rubio" in item and "Ukraine" in item for item in queries)
    assert any("Reuters" in item for item in queries)
    assert any("Kyiv Independent" in item for item in queries)


def test_prepare_fact_check_queries_keeps_spaced_english_query_for_xi_visit_topic() -> None:
    """英文事件查询不应把替换词粘连在一起，也不应残留大段中文噪声。"""

    queries = _prepare_fact_check_queries(
        "习近平可能访问朝鲜，影响地缘政治和东亚资本市场",
        ["习近平可能访问朝鲜，影响地缘政治和东亚资本市场"],
    )

    assert any("Xi Jinping may visit North Korea" in item for item in queries)
    assert all("Jinpingmay" not in item for item in queries)
    assert all("visitNorth" not in item for item in queries)


def test_select_fact_check_queries_limits_budget_but_keeps_site_query() -> None:
    """应限制查询数量，同时尽量保留一个定向站点搜索。"""

    selected = _select_fact_check_queries(
        [
            "query exact",
            "query relaxed",
            "site:reuters.com query relaxed",
            "query extra",
            "site:state.gov query exact",
        ],
        max_queries=3,
    )

    assert len(selected) == 3
    assert "query exact" in selected
    assert "query relaxed" in selected
    assert any(item.startswith("site:") for item in selected)


def test_select_fact_check_queries_prefers_natural_and_wire_queries_for_rubio_topic() -> None:
    """Rubio 话题里应优先保留更像新闻标题且带 Reuters 线索的查询。"""

    selected = _select_fact_check_queries(
        [
            "U.S. Secretary of State Rubio stop mediating talks no progress",
            "Rubio says U.S. will stop mediating Ukraine peace talks",
            "Rubio Ukraine talks no progress Reuters",
            "site:www.reuters.com Rubio says U.S. will stop mediating Ukraine peace talks",
            "site:www.reuters.com Rubio Ukraine talks no progress",
            "site:www.reuters.com U.S. Secretary of State Rubio stop mediating talks no progress",
        ],
        max_queries=4,
    )

    assert "Rubio says U.S. will stop mediating Ukraine peace talks" in selected
    assert "Rubio Ukraine talks no progress Reuters" in selected
    assert "U.S. Secretary of State Rubio stop mediating talks no progress" not in selected
    assert "site:www.reuters.com Rubio says U.S. will stop mediating Ukraine peace talks" in selected
    assert "site:www.reuters.com U.S. Secretary of State Rubio stop mediating talks no progress" not in selected


def test_prepare_fact_check_queries_keeps_site_queries_for_rubio_topic() -> None:
    """复杂政治话题的高价值定向站点搜索不应在查询预算中被提前截掉。"""

    queries = _prepare_fact_check_queries(
        "美国国务卿卢比奥宣布美国退出乌克兰战争调解，称谈判无成果",
        ["美国国务卿卢比奥宣布美国退出乌克兰战争调解，称谈判无成果"],
    )

    assert any(item.startswith("site:www.reuters.com ") for item in queries)
    assert any(item.startswith("site:kyivindependent.com ") for item in queries)


def test_prepare_fact_check_queries_adds_major_media_site_queries_for_market_claim() -> None:
    """财经类说法应主动补充 Bloomberg、WSJ、FT 等大媒体定向搜索。"""

    queries = _prepare_fact_check_queries(
        "宁德时代香港IPO获摩根大通和美国银行支持，引发国际资本市场关注",
        ["宁德时代 香港IPO 摩根大通 美国银行 国际资本市场"],
    )

    assert any(item.startswith("site:www.bloomberg.com ") for item in queries)
    assert any(item.startswith("site:www.wsj.com ") for item in queries)
    assert any(item.startswith("site:www.ft.com ") for item in queries)


def test_prepare_fact_check_queries_does_not_nest_site_prefix() -> None:
    """已带 site: 的查询不应再被重复包成 site:site:。"""

    queries = _prepare_fact_check_queries(
        "美国国会点名摩根大通和美国银行，指控其协助宁德时代在香港IPO",
        ["site:www.hkex.com.hk HKEX IPO filing"],
    )

    assert all("site:www.hkex.com.hk site:www.hkex.com.hk" not in item for item in queries)


def test_normalize_fact_check_claim_strips_known_section_prefixes() -> None:
    """栏目名前缀不应残留到 claim 和后续查询里。"""

    assert _normalize_fact_check_claim("视频观点：沃尔玛估值较高，但增长确定性更强。") == "沃尔玛估值较高，但增长确定性更强。"
    assert _normalize_fact_check_claim("中国经济：中国央行将一年期MLF利率降至1.45%。") == "中国央行将一年期MLF利率降至1.45%。"


def test_prepare_fact_check_queries_adds_specific_queries_for_pboc_mlf_topic() -> None:
    """MLF 题材应补到 PBOC 和国际媒体更具体的英文检索词。"""

    queries = _prepare_fact_check_queries(
        "中国经济：中国央行将一年期MLF利率降至1.45%历史新低，但未公开宣布",
        ["中国央行 一年期MLF 1.45%"],
    )

    assert any("PBOC cuts one-year MLF rate to 1.45%" in item for item in queries)
    assert any("People's Bank of China one-year MLF 1.45%" in item for item in queries)
    assert any(item.startswith("site:www.pbc.gov.cn ") for item in queries)


def test_prepare_fact_check_queries_avoids_rubio_template_for_non_rubio_ukraine_claim() -> None:
    """乌克兰类说法若没有 Rubio，不应被错误改写成 Rubio 查询。"""

    queries = _prepare_fact_check_queries(
        "乌克兰战争：俄罗斯威胁对基辅国防设施进行系统性打击，并敦促外国人离开",
        ["俄罗斯 基辅 国防设施 打击 外国人离开"],
    )

    assert any("Russia threatens strikes on Kyiv defence sites Reuters" in item for item in queries)
    assert any("Russia urges foreigners to leave Kyiv Reuters" in item for item in queries)
    assert all("Rubio" not in item for item in queries)


def test_prepare_fact_check_queries_adds_specific_queries_for_ai_exit_control_topic() -> None:
    """AI 人才边控类说法应补到 Bloomberg/Reuters 风格的具体英文查询。"""

    queries = _prepare_fact_check_queries(
        "AI人才边控：彭博社报道中国将边控扩大至民营AI企业的顶尖人才，护照由公司保管，出国需政府批准",
        ["中国 AI 人才 护照 政府批准 DeepSeek 阿里巴巴"],
    )

    assert any("China expands exit controls to AI talent Bloomberg" in item for item in queries)
    assert any("China AI talent passport controls Alibaba DeepSeek Reuters" in item for item in queries)
    assert any(item.startswith("site:www.bloomberg.com ") for item in queries)


def test_prepare_fact_check_queries_adds_specific_queries_for_yahoo_finance_stock_claim() -> None:
    """雅虎财经三只蓝筹股题材应补到更像原报道标题的检索词。"""

    queries = _prepare_fact_check_queries(
        "财经头条：雅虎财经文章建议市场崩盘时买入三只蓝筹股，包括沃尔玛、Realty Income 和菲利普莫里斯国际",
        ["雅虎财经 三只蓝筹股 沃尔玛 Realty Income 菲利普莫里斯"],
    )

    assert any("Yahoo Finance three blue-chip stocks Walmart Realty Income Philip Morris" in item for item in queries)
    assert any(item.startswith("site:finance.yahoo.com ") for item in queries)


def test_prepare_fact_check_queries_adds_japanese_sources_for_japan_poll_claim() -> None:
    """日本民调类说法应优先补共同社/日经等日本来源。"""

    queries = _prepare_fact_check_queries(
        "日本共同社民调显示高市内阁支持率下降5.5个百分点，39岁以下群体下降13.5个百分点，女性下滑9.2个百分点。",
        ["日本 高市 内阁 支持率 民调"],
    )

    assert any("Kyodo" in item or "共同通信" in item for item in queries)
    assert any(item.startswith("site:english.kyodonews.net ") for item in queries)
    assert any(item.startswith("site:asia.nikkei.com ") for item in queries)


def test_prepare_fact_check_queries_adds_truth_social_for_trump_post_claim() -> None:
    """Trump 发帖类说法应补 Truth Social 定向搜索。"""

    queries = _prepare_fact_check_queries(
        "川普发帖批评意大利总理梅洛尼花费数万亿美元却不保卫美国，梅洛尼未回应。",
        ["川普 Truth Social 梅洛尼 国防开支"],
    )

    assert any("Truth Social" in item for item in queries)
    assert any(item.startswith("site:truthsocial.com ") for item in queries)


def test_prepare_fact_check_queries_adds_polymarket_for_starmer_resignation_claim() -> None:
    """预测市场类说法应补 Polymarket 定向搜索。"""

    queries = _prepare_fact_check_queries(
        "英国首相斯塔默预计将辞职，预测市场Polymarket显示辞职概率达83%。",
        ["英国首相 斯塔默 辞职 Polymarket 83%"],
    )

    assert any("Polymarket Starmer resignation odds" in item for item in queries)
    assert any(item.startswith("site:polymarket.com ") for item in queries)


def test_perform_web_search_drops_generic_chinese_page_when_numeric_claim_has_no_numeric_match(monkeypatch) -> None:
    """涉及具体数字的外文/财经说法，不应保留只蹭到泛地名的中文弱相关页。"""

    monkeypatch.setenv("ANYSEARCH_ENABLED", "0")
    monkeypatch.setattr(
        "core_logic._find_authoritative_sources",
        lambda text: [{"label": "台湾证券交易所", "url": "https://www.twse.com.tw/en/"}],
    )
    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr(
        "core_logic._fetch_bing_web_results",
        lambda query, proxy_url=None, max_items=4: [
            {
                "title": "两岸观察丨 台湾 问题由何而来？",
                "url": "https://taiwan.huanqiu.com/article/4Oq9h1qlBJo",
                "source": "环球网",
                "snippet": "文章讨论台湾历史与政治问题，没有提到股市市值或4.47万亿美元。",
                "published_at": "",
            }
        ],
    )

    rendered = perform_web_search(
        ["台湾股市 4.47万亿美元 加拿大 第六大股市"],
        claim_text="台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市",
    )

    assert "taiwan.huanqiu.com/article/4Oq9h1qlBJo" not in rendered
    assert "台湾证券交易所" in rendered


def test_perform_web_search_does_not_render_nested_site_query_links(monkeypatch) -> None:
    """查询本身已带 site: 时，渲染出的定向搜索链接不应再出现 site:site:。"""

    monkeypatch.setattr(
        "core_logic._find_authoritative_sources",
        lambda text: [{"label": "路透社", "url": "https://www.reuters.com/"}],
    )
    monkeypatch.setattr("core_logic._fetch_bing_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_google_news_results", lambda query, proxy_url=None, max_items=4: [])
    monkeypatch.setattr("core_logic._fetch_bing_web_results", lambda query, proxy_url=None, max_items=4: [])

    rendered = perform_web_search(
        ["site:www.reuters.com Rubio Ukraine talks no progress"],
        claim_text="Rubio Ukraine talks no progress",
    )

    assert "site%3Awww.reuters.com%20site%3Awww.reuters.com" not in rendered
    assert "site%3Awww.reuters.com%20Rubio%20Ukraine%20talks%20no%20progress" in rendered


def test_normalize_fact_check_conclusion_turns_lack_of_evidence_into_dubious_when_hits_exist() -> None:
    """已有候选报道时，不应把条目仍写成“完全缺乏证据”。"""

    fact_md = (
        "### 条目1\n"
        "- 新闻/声明：台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市。\n"
        "- 核查结论：缺乏证据\n"
        "- 依据：未能找到交易所公告直接证实该说法。\n"
    )
    claim_sources = [
        {
            "search_markdown": (
                "### 搜索关键字: 台湾股市 4.47万亿美元 加拿大 第六大股市\n"
                "- 命中的候选报道：\n"
                "  - [台湾股市总市值超加拿大 成为全球第六大股市](https://example.com/news/tw-1)\n"
                "    - 来源：Lianhe Zaobao；时间：Wed, 29 Apr 2026 12:13:00 GMT；摘要：报道称彭博汇编数据显示台湾股市总市值达到4.47万亿美元。\n"
            )
        }
    ]

    normalized = _normalize_fact_check_conclusions_with_sources(fact_md, claim_sources)

    assert "核查结论：存疑" in normalized
    assert "核查结论：缺乏证据" not in normalized
    assert "与该说法对应的新闻报道" in normalized
    assert "台湾股市总市值超加拿大 成为全球第六大股市" in normalized
    assert "交易所公告" not in normalized


def test_normalize_fact_check_conclusion_turns_web_hits_into_dubious() -> None:
    """即使不是新闻 RSS，只要命中了候选网页和官网页面，也不应机械保留“缺乏证据”。"""

    fact_md = (
        "### 条目1\n"
        "- 新闻/声明：某部门发布了相关正式声明。\n"
        "- 核查结论：缺乏证据\n"
        "- 判断依据：现有信息不足以确认。\n"
    )
    claim_sources = [
        {
            "search_markdown": (
                "### 搜索关键字: 部门 正式声明\n"
                "- 命中的候选网页：\n"
                "  - [Official statement](https://www.state.gov/briefing/example)\n"
                "    - 来源：state.gov；摘要：The department published an official statement after the meeting.\n"
                "- 美国国务院 定向命中的候选页面：\n"
                "  - [Department briefing](https://www.state.gov/department-briefing/example)\n"
                "    - 来源：state.gov；摘要：Department briefing transcript.\n"
            )
        }
    ]

    normalized = _normalize_fact_check_conclusions_with_sources(fact_md, claim_sources)

    assert "核查结论：存疑" in normalized
    assert "核查结论：缺乏证据" not in normalized
    assert "官网/机构页面" in normalized
    assert "Official statement" in normalized


def test_normalize_fact_check_conclusion_turns_dynamic_claim_into_dubious_with_partial_support() -> None:
    """即使没显式候选报道列表，只要是动态量化声明且已有来源链接，也应优先判为存疑。"""

    fact_md = (
        "### 条目1\n"
        "- 新闻/声明：台湾股市总市值达到4.47万亿美元，超越加拿大成为全球第六大股市。\n"
        "- 核查结论：缺乏证据\n"
        "- 依据：股市总市值和全球排名是动态变化的，需要来自交易所或权威金融数据机构的实时数据支持。视频未提供可验证的具体数据来源。\n"
        "- 来源/出处：[台湾证券交易所](https://www.twse.com.tw/en/)\n"
    )

    normalized = _normalize_fact_check_conclusions_with_sources(fact_md, [{"search_markdown": ""}])

    assert "核查结论：存疑" in normalized
    assert "核查结论：缺乏证据" not in normalized
    assert "台湾证券交易所" in normalized


def test_normalize_fact_check_conclusion_replaces_generic_exchange_template() -> None:
    """非金融主题命中官网页面时，不应继续保留交易所模板理由。"""

    fact_md = (
        "### 条目1\n"
        "- 新闻/声明：某部门发布了相关正式声明。\n"
        "- 核查结论：缺乏证据\n"
        "- 判断依据：现有候选报道已提供一定间接支持，但仍缺少交易所公告、原始统计口径或一手权威来源的直接确认，因此本条更适合判为“存疑”，而不是“完全缺乏证据”。\n"
    )
    claim_sources = [
        {
            "search_markdown": (
                "### 搜索关键字: 部门 正式声明\n"
                "- 命中的候选网页：\n"
                "  - [Official statement](https://www.state.gov/briefing/example)\n"
                "    - 来源：state.gov；摘要：The department published an official statement after the meeting.\n"
            )
        }
    ]

    normalized = _normalize_fact_check_conclusions_with_sources(fact_md, claim_sources)

    assert "核查结论：存疑" in normalized
    assert "Official statement" in normalized
    assert "交易所公告" not in normalized
    assert "原始统计口径" not in normalized


def test_build_fact_check_fallback_markdown_supports_english_locale() -> None:
    """英文界面下，兜底核查稿也应切到英文结构标签。"""

    fallback = _build_fact_check_fallback_markdown(
        claim_sources=[
            {
                "claim": "Taiwan stock market capitalization reached $4.47 trillion.",
                "queries": ["Taiwan stock market capitalization 4.47 trillion"],
                "search_markdown": "- [Reuters](https://www.reuters.com/)",
            }
        ],
        ui_locale="en-US",
    )

    assert "### Item1" in fallback
    assert "- Claim:" in fallback
    assert "- Conclusion:" in fallback
    assert "- Sources:" in fallback


def test_parse_fact_check_section_supports_english_labels() -> None:
    """英文事实核查输出也应能被页面解析成标题、结论和来源。"""

    from app import _parse_fact_check_section

    parsed = _parse_fact_check_section(
        "### Item 1\n"
        "- Claim: Example claim\n"
        "- Conclusion: Uncertain\n"
        "- Rationale:\n"
        "  - The source headlines are partially supportive.\n"
        "- Follow-up Checks: Confirm the primary filing.\n"
        "- Sources:\n"
        "  - [Reuters](https://www.reuters.com/world/example)\n"
    )

    assert parsed.get("title") == "Example claim"
    assert parsed.get("conclusion") == "Uncertain"
    assert "Confirm the primary filing." in str(parsed.get("pending_markdown") or "")
    assert ("Reuters", "https://www.reuters.com/world/example") in list(parsed.get("source_links") or [])


def test_ensure_fact_check_item_coverage_appends_missing_claim_sections() -> None:
    """模型少输出条目时，应基于剩余声明自动补齐，而不是只展示前几条。"""

    fact_md = (
        "### 条目1\n"
        "- 新闻/声明：声明1\n"
        "- 核查结论：存疑\n"
        "- 判断依据：已有部分公开信息。\n"
        "\n"
        "### 条目2\n"
        "- 新闻/声明：声明2\n"
        "- 核查结论：存疑\n"
        "- 判断依据：已有部分公开信息。\n"
        "\n"
        "### 条目3\n"
        "- 新闻/声明：声明3\n"
        "- 核查结论：存疑\n"
        "- 判断依据：已有部分公开信息。\n"
    )
    claim_sources = [
        {"claim": "声明1", "queries": ["声明1"], "search_markdown": "- [Reuters](https://www.reuters.com/world/1)"},
        {"claim": "声明2", "queries": ["声明2"], "search_markdown": "- [Reuters](https://www.reuters.com/world/2)"},
        {"claim": "声明3", "queries": ["声明3"], "search_markdown": "- [Reuters](https://www.reuters.com/world/3)"},
        {"claim": "声明4", "queries": ["声明4"], "search_markdown": "- [AP](https://apnews.com/4)"},
        {"claim": "声明5", "queries": ["声明5"], "search_markdown": "- [Bloomberg](https://www.bloomberg.com/5)"},
    ]

    completed = _ensure_fact_check_item_coverage(fact_md, claim_sources)

    assert completed.count("### 条目") == 5
    assert "- 新闻/声明： 声明4" not in completed
    assert "- 新闻/声明： 声明5" not in completed
    assert "- 新闻/声明：声明4" in completed
    assert "- 新闻/声明：声明5" in completed


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


def test_build_heuristic_claim_items_prefers_hard_news_over_video_opinion_lines() -> None:
    """回退到 heuristic 抽取时，应优先保留可核查新闻而不是视频观点评论。"""

    summary_md = (
        "## 主要内容\n"
        "- 乌克兰战争：俄罗斯威胁对基辅国防设施进行系统性打击，并敦促外国人离开。\n"
        "- 视频观点：川普将《亚伯拉罕协议》与伊朗停火捆绑，意在转移党内鹰派压力。\n"
    )

    claims = _build_heuristic_claim_items(
        text=summary_md,
        summary_markdown=summary_md,
        max_claims=2,
    )

    assert any("俄罗斯威胁对基辅国防设施进行系统性打击" in item["claim"] for item in claims)
    assert all("亚伯拉罕协议" not in item["claim"] for item in claims)


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


def test_decide_video_fact_check_plan_expands_claim_count_for_dense_news_video() -> None:
    """长新闻/事件类视频应覆盖更多主要声明，而不是固定只核查 5 条。"""

    sentence = (
        "2026 年 5 月，政府部门宣布一项新政策，官方通报 12 个城市参与试点，"
        "记者报道企业回应称已收到监管要求，数据显示相关指标同比变化 18%。"
    )
    transcript = sentence * 90
    summary_md = (
        "## 主要内容\n"
        "- 政府部门宣布新政策并说明试点城市数量。\n"
        "- 官方通报监管要求，企业随后作出公开回应。\n"
        "- 报道引用多组数据对政策影响进行比较。\n"
    )

    plan = decide_video_fact_check_plan(transcript, summary_md)

    assert plan["should_fact_check"] is True
    assert plan["recommended_claim_count"] >= 8
