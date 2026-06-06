# 福生无量天尊 — 共享模块
from openai import OpenAI
import feedparser
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import time
import pytz
import os
import re
import json

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
#  实时行情数据（东方财富公开接口）
# ═══════════════════════════════════════════════════════════════

def _fetch_eastmoney(url, params=None, timeout=10):
    """请求东方财富公开 JSON 接口，失败返回 None"""
    try:
        resp = _session.get(url, params=params, timeout=timeout,
                           headers={"Referer": "https://quote.eastmoney.com/"})
        if resp.status_code != 200:
            print(f"  ⚠️ HTTP {resp.status_code}: {url}")
            return None
        return resp.json()
    except Exception as e:
        print(f"  ⚠️ 行情接口异常: {e}")
        return None


def _sector_kline(sector_code, days=20):
    """获取板块日K线收盘价列表（由旧到新）"""
    url = "http://push2his.eastmoney.com/api/qt/stock/kline/get"
    params = {
        "secid": f"90.{sector_code}",
        "fields1": "f1,f2,f3,f4,f5,f6",
        "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
        "klt": "101",
        "fqt": "1",
        "lmt": str(days),
    }
    data = _fetch_eastmoney(url, params, timeout=8)
    if not data or not data.get("data") or not data["data"].get("klines"):
        return []
    closes = []
    for line in data["data"]["klines"]:
        parts = line.split(",")
        if len(parts) >= 3 and parts[2]:
            closes.append(float(parts[2]))
    return closes


def _period_ret(closes, period):
    """计算区间涨跌幅（%），closes 从旧到新。不足 period+1 根K线返回 None"""
    if len(closes) < period + 1:
        return None
    return (closes[-1] - closes[-period - 1]) / closes[-period - 1] * 100


def _fetch_board(fs_filter, board_label, top_n=12, kline_n=5):
    """获取板块排名 + 头部板块多周期涨跌幅"""
    url = "http://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "fid": "f3",
        "po": "1",
        "pz": "100",
        "pn": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": fs_filter,
        "fields": "f2,f3,f4,f12,f14,f62,f184",
    }
    data = _fetch_eastmoney(url, params)
    if not data or not data.get("data") or not data["data"].get("diff"):
        return ""

    items = data["data"]["diff"]
    # 过滤涨跌幅为 None 的条目
    valid = [i for i in items if i.get("f3") is not None]
    if not valid:
        return ""
    valid.sort(key=lambda x: x["f3"], reverse=True)

    gainers = valid[:top_n]
    losers = valid[-top_n:] if len(valid) >= top_n else []

    # 获取头部板块 K 线（多周期涨跌幅）
    klines = {}
    targets = valid[:kline_n] + valid[-kline_n:] if len(valid) >= kline_n else valid[:kline_n]
    for item in targets:
        code = item.get("f12", "")
        if code and code not in klines:
            klines[code] = _sector_kline(code, 20)

    lines = [
        f"### {board_label}",
        "",
        "| 排名 | 板块 | 今日涨跌幅 | 近3日 | 近5日 | 近2周 | 近20日 | 主力净流入(亿) |",
        "|------|------|-----------|-------|-------|-------|--------|---------------|",
    ]

    shown = set()
    rank = 0
    for item in gainers + losers:
        code = item.get("f12", "")
        name = item.get("f14", "")
        if code in shown:
            continue
        shown.add(code)
        rank += 1

        chg = item.get("f3") or 0
        inflow = (item.get("f62") or 0) / 1e8

        c = klines.get(code, [])
        r3 = _period_ret(c, 3)
        r5 = _period_ret(c, 5)
        r10 = _period_ret(c, 10)
        r20 = _period_ret(c, 20)

        def _f(v):
            return f"{v:+.2f}%" if v is not None else "-"

        lines.append(
            f"| {rank} | {name} | {_f(chg)} | {_f(r3)} | {_f(r5)} "
            f"| {_f(r10)} | {_f(r20)} | {inflow:+.2f} |"
        )

    return "\n".join(lines)


def _fetch_indices():
    """主要指数行情"""
    url = "http://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "fid": "f3",
        "po": "1",
        "pz": "20",
        "pn": "1",
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fs": "m:0+t:index,m:1+t:index",
        "fields": "f2,f3,f4,f12,f14",
    }
    data = _fetch_eastmoney(url, params)
    if not data or not data.get("data") or not data["data"].get("diff"):
        return ""

    watch = {
        "000001": "上证指数", "399001": "深证成指", "399006": "创业板指",
        "000688": "科创50", "000300": "沪深300", "000905": "中证500",
        "000016": "上证50", "399673": "创业板50",
    }

    lines = [
        "### 主要指数",
        "",
        "| 指数 | 最新价 | 涨跌幅 | 涨跌额 |",
        "|------|--------|--------|--------|",
    ]
    for item in data["data"]["diff"]:
        code = item.get("f12", "")
        name = watch.get(code, item.get("f14", code))
        price = item.get("f2", "-")
        chg_p = item.get("f3") or 0
        chg_a = item.get("f4") or 0
        lines.append(f"| {name} | {price} | {chg_p:+.2f}% | {chg_a:+.2f} |")
    return "\n".join(lines)


def _fetch_north_bound():
    """北向资金近 5 日流向"""
    url = "http://push2.eastmoney.com/api/qt/kamt.kline/get"
    params = {
        "fields1": "f1,f2,f3,f4",
        "fields2": "f51,f52,f53",
        "klt": "101",
        "lmt": "5",
    }
    data = _fetch_eastmoney(url, params)
    if not data or not data.get("data") or not data["data"].get("klines"):
        return ""

    lines = [
        "### 北向资金（近5日）",
        "",
        "| 日期 | 沪股通净流入(亿) | 深股通净流入(亿) | 合计(亿) |",
        "|------|-----------------|-----------------|---------|",
    ]
    for line in data["data"]["klines"]:
        parts = line.split(",")
        if len(parts) >= 3:
            date = parts[0]
            sh = float(parts[1]) / 1e8 if parts[1] else 0
            sz = float(parts[2]) / 1e8 if parts[2] else 0
            lines.append(f"| {date} | {sh:+.2f} | {sz:+.2f} | {sh + sz:+.2f} |")
    return "\n".join(lines)


def fetch_market_data():
    """获取实时行情数据，返回格式化 Markdown 文本"""
    print("📊 正在获取实时行情数据...")
    parts = []

    for label, func in [
        ("指数", _fetch_indices),
        ("行业板块", lambda: _fetch_board("m:90+t2", "行业板块（申万）")),
        ("概念板块", lambda: _fetch_board("m:90+t3", "概念板块")),
        ("北向资金", _fetch_north_bound),
    ]:
        try:
            result = func()
            if result:
                parts.append(result)
                print(f"  ✅ {label}")
            else:
                print(f"  ⚠️ {label}: 无数据")
        except Exception as e:
            print(f"  ❌ {label}: {e}")

    if parts:
        tz = pytz.timezone("Asia/Shanghai")
        now = datetime.now(tz).strftime("%Y-%m-%d %H:%M")
        header = f"## 📊 实时行情数据（获取时间：{now} 北京时间）\n"
        return header + "\n\n".join(parts)
    return ""


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
以下规则是硬约束，违反任何一条即为不合格输出。

══════════════════════════════════════
〇、输出格式铁律 —— 第一优先级
══════════════════════════════════════

禁止一切开场白。你的第一行输出必须是"📊 热点速览"标题。
禁止以下任何形式的开头：
- "好的"、"好的，"、"根据"、"以下是"、"总结如下"
- "作为一名..."、"我将..."、"让我..."
- 任何对指令的复述或确认
违者直接重写整个输出。

══════════════════════════════════════
一、数据先行 —— 缺数据就别说"热点"
══════════════════════════════════════

每个行业/主题必须附带具体数字，格式统一为：
"根据[数据源]，XX行业今日涨跌幅 +X.XX%，近3日累计 +X.XX%，此前2周累计 -X.XX%（或+X.XX%），区间成交额XXX亿，环比变化±XX%。"

没有数据支撑，禁止使用"涨幅最高""领涨""爆发"等排序词。
排名必须先查数再下结论，不允许先下结论再编排名。

一个"行业/主题"至少要有3只及以上代表性标的同步异动，才能被列为热点方向。仅凭一家公司发公告就被列成行业热点，视为凑数，直接删除。

══════════════════════════════════════
二、引用可查证来源 —— 不允许"市场认为"
══════════════════════════════════════

每个深度分析段落至少引用一个可查证的外部数据源。
允许的类型：申万行业指数、万得概念板块涨跌幅、北向资金行业分布、龙虎榜机构席位、期货主力合约收盘价、波罗的海干散货指数、一致预期EPS变化率、ETF资金流向等。

禁止的写法："市场普遍认为""资金可能""投资者预期""有分析指出"——出现任何一句，整段重写。
如果新闻中没有提供可查证数据，就只做定性摘要，不要假装有数据支撑。

══════════════════════════════════════
三、结论三段论 —— 缺一不可
══════════════════════════════════════

每个热点方向必须回答三个问题：
1. 买什么：具体到子板块、产业链环节或龙头标的名称，不是"国产算力有前途"这种大话。
2. 什么时候买：现在是右侧确认还是左侧埋伏？催化剂时间窗口在哪（如"等XX数据公布后确认"）？
3. 什么时候卖：止损/止盈条件是什么？需要盯住什么信号来退场？

做不到以上三条就不要给投资建议。最终统一标注"⚠️ 以上分析仅供信息参考，不构成投资建议"。

══════════════════════════════════════
四、风险提示 —— 概率化，不要精神分裂
══════════════════════════════════════

风险提示必须与前文逻辑自洽。给出情景概率：
"基准情景（XX%概率）：……，板块有XX%-XX%上行空间。风险情景（XX%概率）：……，可能在XX时间内回撤XX%。建议以XX仓位参与，设XX止损线。"

不允许前文说"趋势确立"，风险提示又写"可能崩塌式回落"——这种前后矛盾的输出直接判不及格。

══════════════════════════════════════
五、输出格式要求
══════════════════════════════════════

1. 开头用卡片格式列出热点（禁止使用Markdown表格，微信不支持表格渲染）：

**1. 行业名称**（今日 ±X.X%，近3日 ±X.X%，此前2周 ±X.X%）
龙头：XX股份、XX科技
驱动：一句话核心逻辑

**2. 行业名称**（今日 ±X.X%，近3日 ±X.X%，此前2周 ±X.X%）
龙头：XX股份
驱动：一句话核心逻辑

...最多列6个热点，每个热点之间空一行

2. 每个深度分析前加一行加粗的「一句话核心矛盾」：
"**核心矛盾**：市场在交易[XX预期拐点]。核心看[XX指标]的变化。"

3. 严格区分"事实"和"观点"：
- 事实写法（OK）："本周纳指跌X%+北向资金净卖出科技板块Y亿"
- 观点写法（禁止伪装成事实）："资金正在撤离高估值科技股"

══════════════════════════════════════
六、核心铁律
══════════════════════════════════════

每一段分析，里面至少塞入：一个数字、一个标的名称、一个可验证的判断。
没有这三样东西的段落，直接删掉。

══════════════════════════════════════
七、长度与结构
══════════════════════════════════════

最终输出控制在1500字以内。结构：
1. 热点速览（卡片格式）
2. 深度分析（3-6个方向，每个含核心矛盾+催化剂+复盘+展望+风险情景概率）
3. 一句话总结

如果新闻数据不足以支撑某条规则的要求，宁可跳过该热点，也不要用模糊语言敷衍。
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
#  工具函数
# ═══════════════════════════════════════════════════════════════

def today_date():
    return datetime.now(pytz.timezone("Asia/Shanghai")).date()
