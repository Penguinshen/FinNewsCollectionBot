# 福生无量天尊 — 国内财经新闻
from common import (
    fetch_rss_articles, fetch_market_data, summarize,
    send_to_wechat, today_date,
)

rss_feeds = {
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
            "以下是今日国内财经新闻原文：\n\n"
            f"{analysis_text}"
        )
    else:
        print("⚠️ 未获取到行情数据，仅使用新闻原文分析")
        full_analysis = analysis_text

    summary = summarize(full_analysis)

    final_summary = (
        f"📅 **{today_str} 国内财经新闻摘要**\n\n"
        f"✍️ **今日分析总结：**\n{summary}\n\n---\n\n"
    )
    for category, content in articles_data.items():
        if content.strip():
            final_summary += f"## {category}\n{content}\n\n"

    send_to_wechat(title=f"🇨🇳 {today_str} 国内财经新闻摘要", content=final_summary)
