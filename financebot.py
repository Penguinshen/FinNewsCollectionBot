# 福生无量天尊
from openai import OpenAI
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
import pytz
import os
import re

# ── 浏览器 User-Agent（模拟 Chrome/Win） ──────────────────────
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
}

# ── 全局 requests 会话（复用连接） ──────────────────────────
_session = requests.Session()
_session.headers.update(BROWSER_HEADERS)

# OpenAI API Key
openai_api_key = os.getenv("OPENAI_API_KEY")
# 从环境变量获取 Server酱 SendKeys（兼容旧版 Server酱和 Server酱3）
server_chan_keys_env = os.getenv("SERVER_CHAN_KEYS") or os.getenv("SERVERCHAN3_SENDKEY")
if not server_chan_keys_env:
    raise ValueError("环境变量 SERVER_CHAN_KEYS 或 SERVERCHAN3_SENDKEY 未设置，请在Github Actions中设置此变量！")
server_chan_keys = server_chan_keys_env.split(",")

openai_client = OpenAI(api_key=openai_api_key, base_url="https://api.deepseek.com/v1")

# ── RSS源地址列表 ────────────────────────────────────────────
rss_feeds = {
    "💲 华尔街见闻": {
        "华尔街见闻": "https://dedicated.wallstreetcn.com/rss.xml",
    },
    "💻 36氪": {
        "36氪": "https://36kr.com/feed",
    },
    "🇨🇳 中国经济": {
        "香港經濟日報": "https://www.hket.com/rss/china",
        "东方财富": "http://rss.eastmoney.com/rss_partener.xml",
        "百度股票焦点": "http://news.baidu.com/n?cmd=1&class=stock&tn=rss&sub=0",
        "中新网": "https://www.chinanews.com.cn/rss/finance.xml",
        "国家统计局-最新发布": "https://www.stats.gov.cn/sj/zxfb/rss.xml",
    },
    "🇺🇸 美国经济": {
        "华尔街日报 - 经济": "https://feeds.content.dowjones.io/public/rss/WSJcomUSBusiness",
        "华尔街日报 - 市场": "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain",
        "MarketWatch美股": "https://www.marketwatch.com/rss/topstories",
        "ZeroHedge华尔街新闻": "https://feeds.feedburner.com/zerohedge/feed",
        "ETF Trends": "https://www.etftrends.com/feed/",
    },
    "🌍 世界经济": {
        "华尔街日报 - 经济": "https://feeds.content.dowjones.io/public/rss/socialeconomyfeed",
        "BBC全球经济": "http://feeds.bbci.co.uk/news/business/rss.xml",
    },
}


# ═══════════════════════════════════════════════════════════════
#  站点级正文提取规则
# ═══════════════════════════════════════════════════════════════

# 每个域名对应一组 CSS 选择器，按优先级排列（第一个命中即返回）
SITE_SELECTORS = {
    "wallstreetcn.com": [
        "div.article-body",
        "div.article__content",
        "article .rich-text",
        "div.rich-text",
    ],
    "36kr.com": [
        "div.article-detail-content",
        "div.article-content",
        "article div.common-width",
        "div.common-width.content",
    ],
    "eastmoney.com": [
        "div.newsContent",
        "#ContentBody",
        "div.article-content",
        "div.detail-content",
    ],
    "chinanews.com.cn": [
        "div.left_zw",
        "div.content",
        "#cont_1_1_2",
        "article",
    ],
    "chinanews.com": [  # 部分 RSS 用短域名
        "div.left_zw",
        "div.content",
        "article",
    ],
    "stats.gov.cn": [
        "div.TRS_Editor",
        "div.TRS_UEDITOR",
        "#zoom",
        "div.content",
    ],
    "hket.com": [
        "div.article-content",
        "div.article-body",
        "div.content",
        "article",
    ],
    "news.baidu.com": [
        "div.article-content",
        "div.article-body",
        "p",  # 百度新闻页结构简单
    ],
    "wsj.com": [
        "section.article-content",
        "div.article-content",
        "div.wsj-snippet-body",
        "article p",
    ],
    "marketwatch.com": [
        "div.article__body",
        "div.article-content",
        "article div.region--body",
    ],
    "zerohedge.com": [
        "div.post-content",
        "div.article-body",
        "div.content",
    ],
    "bbc.co.uk": [
        "article div.story-body__inner",
        "div.story-body",
        "article",
    ],
    "bbc.com": [
        "article div.story-body__inner",
        "div.story-body",
        "article",
    ],
    "etftrends.com": [
        "div.entry-content",
        "div.post-content",
        "article",
    ],
}


def _extract_by_selectors(soup, selectors):
    """用一组 CSS 选择器尝试提取正文，返回纯文本或 None"""
    for sel in selectors:
        container = soup.select_one(sel)
        if not container:
            continue
        # 移除脚本/样式/隐藏元素
        for tag in container.select("script, style, noscript, .hidden, [style*='display:none']"):
            tag.decompose()
        text = container.get_text(separator="\n", strip=True)
        if text and len(text) > 80:
            return text
    return None


def _extract_generic(soup):
    """通用提取：og:description → meta description → <article> → <p> 集合"""
    # 1) Open Graph description
    og = soup.find("meta", property="og:description")
    if og and og.get("content"):
        return og["content"].strip()

    # 2) meta description
    meta = soup.find("meta", attrs={"name": "description"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    # 3) <article> 标签
    article = soup.find("article")
    if article:
        for tag in article.select("script, style, noscript"):
            tag.decompose()
        text = article.get_text(separator="\n", strip=True)
        if text and len(text) > 100:
            return text

    # 4) 收集所有 <p>，按文本密度选最长的连续块
    paragraphs = []
    for p in soup.find_all("p"):
        t = p.get_text(strip=True)
        if len(t) > 20:
            paragraphs.append(t)

    if paragraphs:
        return "\n".join(paragraphs[:30])  # 最多取 30 段

    # 5) 最后兜底：body 全文（截断）
    body = soup.find("body")
    if body:
        return body.get_text(separator="\n", strip=True)[:3000]

    return ""


# ═══════════════════════════════════════════════════════════════
#  正文抓取（请求 + 解析）
# ═══════════════════════════════════════════════════════════════

def fetch_article_text(url, max_chars=1500, timeout=15):
    """
    下载网页 → 站点级选择器 → 通用提取 → 截断返回
    返回纯文本，失败返回占位字符串
    """
    try:
        print(f"📰 正在爬取: {url}")
        resp = _session.get(url, timeout=timeout, allow_redirects=True)

        # 非 200 直接放弃
        if resp.status_code != 200:
            print(f"⚠️ HTTP {resp.status_code}: {url}")
            return _empty_fallback()

        # 自动检测编码
        resp.encoding = resp.apparent_encoding or "utf-8"
        html = resp.text

        if len(html) < 300:
            print(f"⚠️ 页面内容过短（{len(html)} 字节）: {url}")
            return _empty_fallback()

        soup = BeautifulSoup(html, "lxml")

        # 1) 按域名匹配站点规则
        from urllib.parse import urlparse
        domain = urlparse(url).netloc.lower()
        # 去掉 www. 前缀做模糊匹配
        domain_clean = domain.replace("www.", "")

        for site_domain, selectors in SITE_SELECTORS.items():
            if site_domain in domain_clean:
                text = _extract_by_selectors(soup, selectors)
                if text:
                    print(f"  ✅ 站点规则命中 [{site_domain}] → {len(text)} 字")
                    return text[:max_chars]

        # 2) 通用提取
        text = _extract_generic(soup)
        if text:
            print(f"  ✅ 通用提取 → {len(text)} 字")
            return text[:max_chars]

        print(f"  ⚠️ 未能提取正文: {url}")
        return _empty_fallback()

    except requests.Timeout:
        print(f"  ❌ 请求超时: {url}")
        return _empty_fallback()
    except requests.RequestException as e:
        print(f"  ❌ 网络错误: {url} → {e}")
        return _empty_fallback()
    except Exception as e:
        print(f"  ❌ 解析失败: {url} → {e}")
        return _empty_fallback()


def _empty_fallback():
    return "（未能获取文章正文）"


# ═══════════════════════════════════════════════════════════════
#  RSS 抓取
# ═══════════════════════════════════════════════════════════════

def fetch_feed_with_headers(url):
    """带浏览器头抓 RSS"""
    return feedparser.parse(url, request_headers=BROWSER_HEADERS)


def fetch_feed_with_retry(url, retries=3, delay=5):
    """自动重试获取 RSS"""
    for i in range(retries):
        try:
            feed = fetch_feed_with_headers(url)
            if feed and hasattr(feed, "entries") and len(feed.entries) > 0:
                return feed
        except Exception as e:
            print(f"⚠️ 第 {i+1} 次请求 {url} 失败: {e}")
            time.sleep(delay)
    print(f"❌ 跳过 {url}, 尝试 {retries} 次后仍失败。")
    return None


def fetch_rss_articles(rss_feeds, max_articles=10):
    """遍历 RSS 源，抓取标题 + 正文（正文仅用于 AI 分析，不展示）"""
    news_data = {}
    analysis_text = ""

    for category, sources in rss_feeds.items():
        category_content = ""
        for source, url in sources.items():
            print(f"📡 正在获取 {source} 的 RSS 源: {url}")
            feed = fetch_feed_with_retry(url)
            if not feed:
                print(f"⚠️ 无法获取 {source} 的 RSS 数据")
                continue
            print(f"✅ {source} RSS 获取成功，共 {len(feed.entries)} 条新闻")

            articles = []
            for entry in feed.entries[:5]:
                title = entry.get("title", "无标题")
                link = entry.get("link", "") or entry.get("guid", "")
                if not link:
                    print(f"⚠️ {source} 的新闻 '{title}' 没有链接，跳过")
                    continue

                article_text = fetch_article_text(link)
                analysis_text += f"【{title}】\n{article_text}\n\n"

                print(f"🔹 {source} - {title}")
                articles.append(f"- [{title}]({link})")

            if articles:
                category_content += f"### {source}\n" + "\n".join(articles) + "\n\n"

        news_data[category] = category_content

    return news_data, analysis_text


# ═══════════════════════════════════════════════════════════════
#  AI 摘要 & 推送
# ═══════════════════════════════════════════════════════════════

def summarize(text):
    """调用 DeepSeek 生成财经热点摘要"""
    completion = openai_client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {
                "role": "system",
                "content": """
你是一名专业的财经新闻分析师，请根据以下新闻内容，按照以下步骤完成任务：
1. 提取新闻中涉及的主要行业和主题，找出近1天涨幅最高的3个行业或主题，以及近3天涨幅较高且此前2周表现平淡的3个行业/主题。（如新闻未提供具体涨幅，请结合描述和市场情绪推测热点）
2. 针对每个热点，输出：
   - 催化剂：分析近期上涨的可能原因（政策、数据、事件、情绪等）。
   - 复盘：梳理过去3个月该行业/主题的核心逻辑、关键动态与阶段性走势。
   - 展望：判断该热点是短期炒作还是有持续行情潜力。
3. 将以上分析整合为一篇1500字以内的财经热点摘要，逻辑清晰、重点突出，适合专业投资者阅读。
""",
            },
            {"role": "user", "content": text},
        ],
    )
    return completion.choices[0].message.content.strip()


def send_to_wechat(title, content):
    """推送到微信（兼容旧版 Server酱 和 Server酱3）"""
    for key in server_chan_keys:
        key = key.strip()
        if key.startswith("sctp"):
            match = re.match(r"sctp(\d+)t", key)
            if match:
                url = f"https://{match.group(1)}.push.ft07.com/send/{key}.send"
            else:
                print(f"❌ 无效的 Server酱3 key 格式: {key}")
                continue
        else:
            url = f"https://sctapi.ftqq.com/{key}.send"
        params = {"title": title, "desp": content, "options": {}}
        headers = {"Content-Type": "application/json;charset=utf-8"}
        response = requests.post(url, json=params, headers=headers, timeout=10)
        if response.ok:
            print(f"✅ 推送成功: {key[:15]}...")
        else:
            print(f"❌ 推送失败: {key[:15]}..., 响应：{response.text}")


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

def today_date():
    return datetime.now(pytz.timezone("Asia/Shanghai")).date()


if __name__ == "__main__":
    today_str = today_date().strftime("%Y-%m-%d")

    articles_data, analysis_text = fetch_rss_articles(rss_feeds, max_articles=5)

    summary = summarize(analysis_text)

    final_summary = (
        f"📅 **{today_str} 财经新闻摘要**\n\n"
        f"✍️ **今日分析总结：**\n{summary}\n\n---\n\n"
    )
    for category, content in articles_data.items():
        if content.strip():
            final_summary += f"## {category}\n{content}\n\n"

    send_to_wechat(title=f"📌 {today_str} 财经新闻摘要", content=final_summary)
