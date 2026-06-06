# 福生无量天尊 — 国际财经新闻
from common import (
    fetch_rss_articles, fetch_market_data, summarize,
    send_to_wechat, today_date,
)

rss_feeds = {
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

if __name__ == "__main__":
    today_str = today_date().strftime("%Y-%m-%d")

    articles_data, analysis_text = fetch_rss_articles(rss_feeds, max_articles=5)

    market_data = fetch_market_data()
    if market_data:
        full_analysis = (
            "以下是今日实时行情数据，请严格使用这些数据进行分析。\n"
            "禁止编造或猜测未提供的数字；缺失数据在表格中标注\"-\"。\n\n"
            f"{market_data}\n\n"
            "---\n\n"
            "以下是今日国际财经新闻原文：\n\n"
            f"{analysis_text}"
        )
    else:
        print("⚠️ 未获取到行情数据，仅使用新闻原文分析")
        full_analysis = analysis_text

    summary = summarize(full_analysis)

    final_summary = (
        f"📅 **{today_str} 国际财经新闻摘要**\n\n"
        f"✍️ **今日分析总结：**\n{summary}\n\n---\n\n"
    )
    for category, content in articles_data.items():
        if content.strip():
            final_summary += f"## {category}\n{content}\n\n"

    send_to_wechat(title=f"🌍 {today_str} 国际财经新闻摘要", content=final_summary)
