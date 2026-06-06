# 福生无量天尊 — 国内+国际合并推送
from common import (
    fetch_rss_articles, fetch_market_data, summarize,
    send_to_wechat, today_date,
)

# ── 国内 RSS 源 ──────────────────────────────────────────
rss_feeds_cn = {
    "💲 华尔街见闻": {
        "华尔街见闻": "https://dedicated.wallstreetcn.com/rss.xml",
    },
    "💻 36氪": {
        "36氪": "https://36kr.com/feed",
    },
    "🇨🇳 中国经济": {
        "东方财富": "http://rss.eastmoney.com/rss_partener.xml",
        "中新网": "https://www.chinanews.com.cn/rss/finance.xml",
        "国家统计局-最新发布": "https://www.stats.gov.cn/sj/zxfb/rss.xml",
    },
}

# ── 国际 RSS 源 ──────────────────────────────────────────
rss_feeds_global = {
    "🇺🇸 美国经济": {
        "华尔街日报 - 经济": "https://feeds.content.dowjones.io/public/rss/WSJcomUSBusiness",
        "华尔街日报 - 市场": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",
        "MarketWatch美股": "https://www.marketwatch.com/rss/topstories",
        "ZeroHedge华尔街新闻": "https://feeds.feedburner.com/zerohedge/feed",
        "ETF Trends": "https://www.etftrends.com/feed/",
    },
    "🌍 世界经济": {
        "华尔街日报 - 全球经济": "https://feeds.content.dowjones.io/public/rss/socialeconomyfeed",
        "BBC全球经济": "http://feeds.bbci.co.uk/news/business/rss.xml",
    },
}

# ── 分析单个市场的新闻 ───────────────────────────────────
def analyze_market(rss_feeds, market_label):
    """抓取新闻 + 行情数据 → AI 摘要，返回 (articles_data, summary)"""
    articles_data, analysis_text = fetch_rss_articles(rss_feeds, max_articles=5)

    market_data = fetch_market_data()
    if market_data:
        full_analysis = (
            "以下是今日实时行情数据，请严格使用这些数据进行分析。\n"
            "禁止编造或猜测未提供的数字；缺失数据在表格中标注\"-\"。\n\n"
            f"{market_data}\n\n"
            "---\n\n"
            f"以下是今日{market_label}财经新闻原文：\n\n"
            f"{analysis_text}"
        )
    else:
        print(f"⚠️ 未获取到行情数据，仅使用{market_label}新闻原文分析")
        full_analysis = analysis_text

    summary = summarize(full_analysis)
    return articles_data, summary


# ── 构建文章链接区 ────────────────────────────────────────
def build_articles_section(articles_data):
    """把文章链接拼成 Markdown"""
    lines = []
    for category, content in articles_data.items():
        if content.strip():
            lines.append(f"## {category}\n{content}\n")
    return "\n".join(lines)


if __name__ == "__main__":
    today_str = today_date().strftime("%Y-%m-%d")

    # ── 国内 ──────────────────────────────────────────
    print("\n========== 🇨🇳 开始处理国内新闻 ==========\n")
    try:
        cn_articles, cn_summary = analyze_market(rss_feeds_cn, "国内")
        cn_links = build_articles_section(cn_articles)
        cn_block = (
            f"🇨🇳 **{today_str} 国内财经新闻摘要**\n\n"
            f"📅 **{today_str} 国内财经新闻摘要**\n\n"
            f"✍️ **今日分析总结：**\n{cn_summary}\n\n---\n\n"
            f"{cn_links}"
        )
        print("✅ 国内新闻处理完成")
    except Exception as e:
        print(f"❌ 国内新闻处理失败: {e}")
        cn_block = f"🇨🇳 **{today_str} 国内财经新闻摘要**\n\n⚠️ 今日国内新闻获取失败，请检查日志。\n"

    # ── 国际 ──────────────────────────────────────────
    print("\n========== 🌍 开始处理国际新闻 ==========\n")
    try:
        global_articles, global_summary = analyze_market(rss_feeds_global, "国际")
        global_links = build_articles_section(global_articles)
        global_block = (
            f"🌍 **{today_str} 国际财经新闻摘要**\n\n"
            f"📅 **{today_str} 国际财经新闻摘要**\n\n"
            f"✍️ **今日分析总结：**\n{global_summary}\n\n---\n\n"
            f"{global_links}"
        )
        print("✅ 国际新闻处理完成")
    except Exception as e:
        print(f"❌ 国际新闻处理失败: {e}")
        global_block = f"🌍 **{today_str} 国际财经新闻摘要**\n\n⚠️ 今日国际新闻获取失败，请检查日志。\n"

    # ── 合并推送 ──────────────────────────────────────
    final_content = cn_block + "\n\n\n" + global_block
    send_to_wechat(
        title=f"📌 {today_str} 财经新闻摘要（国内+国际）",
        content=final_content,
    )
