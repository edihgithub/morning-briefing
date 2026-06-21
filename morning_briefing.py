import yfinance as yf
import smtplib
import os
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import pytz
from deep_translator import GoogleTranslator

JST = pytz.timezone("Asia/Tokyo")

TICKERS = {
    "S&P 500": "^GSPC",
    "ダウ平均": "^DJI",
    "ナスダック総合": "^IXIC",
}
WTI_TICKER = "CL=F"


def get_market_data(symbol, days=60):
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period=f"{days}d")
    hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
    if len(hist) < 2:
        return None

    latest = hist.iloc[-1]
    prev = hist.iloc[-2]

    o, h, l, c = latest["Open"], latest["High"], latest["Low"], latest["Close"]
    prev_c = prev["Close"]
    change = c - prev_c
    change_pct = (change / prev_c) * 100
    candle = "陽線" if c > o else "陰線"
    movement = describe_movement(o, h, l, c, prev_c)

    # チャート用OHLC履歴（直近30日分）
    chart_data = []
    for dt, row in hist.tail(30).iterrows():
        chart_data.append({
            "time": dt.strftime("%Y-%m-%d"),
            "open": round(row["Open"], 2),
            "high": round(row["High"], 2),
            "low": round(row["Low"], 2),
            "close": round(row["Close"], 2),
        })

    return {
        "open": o, "high": h, "low": l, "close": c,
        "change": change, "change_pct": change_pct,
        "candle": candle, "movement": movement,
        "date": hist.index[-1].strftime("%Y-%m-%d"),
        "chart_data": chart_data,
    }


def describe_movement(o, h, l, c, prev_c):
    body = abs(c - o)
    upper_shadow = h - max(o, c)
    lower_shadow = min(o, c) - l
    is_bull = c > o
    gap_up = o > prev_c * 1.003
    gap_down = o < prev_c * 0.997

    parts = []
    if gap_up:
        parts.append("ギャップアップで寄り付き")
    elif gap_down:
        parts.append("ギャップダウンで寄り付き")
    else:
        parts.append("前日終値付近で寄り付き")

    if is_bull:
        if upper_shadow > body * 0.7:
            parts.append("高値圏で上ヒゲを残し上昇幅を縮めて引け")
        elif lower_shadow > body * 0.5:
            parts.append("下値を試した後に切り返し上昇して引け")
        else:
            parts.append("終日堅調に推移して引け")
    else:
        if lower_shadow > body * 0.7:
            parts.append("下ヒゲを残し下落幅を縮めて引け")
        elif upper_shadow > body * 0.5:
            parts.append("前半上昇も後半失速し下落して引け")
        else:
            parts.append("終日軟調に推移して引け")

    return "、".join(parts)


def translate_to_japanese(text):
    try:
        return GoogleTranslator(source="auto", target="ja").translate(text)
    except Exception:
        return text


def get_news():
    ticker = yf.Ticker("^GSPC")
    news_items = ticker.news or []
    results = []
    for item in news_items[:5]:
        content = item.get("content", {})
        title = content.get("title") or item.get("title", "")
        url = (content.get("canonicalUrl", {}) or {}).get("url") or item.get("link", "")
        if title:
            translated = translate_to_japanese(title)
            results.append({"title": translated, "url": url})
    return results


def build_email_body(market_data, wti_data, news_items, today_str, pages_url):
    sign = lambda x: f"+{x:.2f}" if x >= 0 else f"{x:.2f}"

    lines = [
        f"【朝の株式マーケットブリーフィング】{today_str}",
        f"ビジュアル表示: {pages_url}",
        "",
        "=" * 40,
        "米国株式市場（前日終値）",
        "=" * 40,
    ]

    for name, data in market_data.items():
        if data is None:
            lines += [f"\n■ {name}", "  データ取得失敗"]
            continue
        lines += [
            f"\n■ {name}（{data['date']}）",
            f"  終値：{data['close']:,.2f}　({sign(data['change'])} / {sign(data['change_pct'])}%)",
            f"  始値：{data['open']:,.2f}　高値：{data['high']:,.2f}　安値：{data['low']:,.2f}",
            f"  ローソク足：{data['candle']}",
            f"  値動き：{data['movement']}",
        ]

    lines += ["", "=" * 40, "WTI原油（CL=F）", "=" * 40]
    if wti_data:
        lines += [
            f"\n  価格：{wti_data['close']:.2f} USD　({sign(wti_data['change'])} / {sign(wti_data['change_pct'])}%)",
            f"  ローソク足：{wti_data['candle']}",
            f"  値動き：{wti_data['movement']}",
        ]
    else:
        lines.append("  データ取得失敗")

    lines += ["", "=" * 40, "市場関連ニュース（上位5件）", "=" * 40]
    if news_items:
        for i, item in enumerate(news_items, 1):
            lines.append(f"\n  {i}. {item['title']}")
            if item["url"]:
                lines.append(f"     {item['url']}")
    else:
        lines.append("  ニュース取得失敗")

    lines += [
        "",
        "=" * 40,
        "本日の注目予定",
        "=" * 40,
        "  https://jp.investing.com/economic-calendar/",
        "",
        "-" * 40,
        "このメールはGitHub Actionsにより自動送信されました。",
    ]
    return "\n".join(lines)


def generate_html(market_data, wti_data, news_items, today_str):
    sign = lambda x: (f"+{x:.2f}" if x >= 0 else f"{x:.2f}")
    color = lambda x: "#26a69a" if x >= 0 else "#ef5350"

    def card(name, data):
        if data is None:
            return f'<div class="card"><h2>{name}</h2><p>データ取得失敗</p></div>'
        c = color(data["change_pct"])
        chart_json = json.dumps(data["chart_data"])
        chart_id = name.replace(" ", "_").replace("&", "")
        return f"""
<div class="card">
  <h2>{name}</h2>
  <div class="price">{data['close']:,.2f}
    <span class="change" style="color:{c}">{sign(data['change'])} ({sign(data['change_pct'])}%)</span>
  </div>
  <div class="meta">
    <span class="tag" style="background:{c}">{data['candle']}</span>
    {data['movement']}
  </div>
  <div class="ohlc">始値 {data['open']:,.2f} ／ 高値 {data['high']:,.2f} ／ 安値 {data['low']:,.2f}</div>
  <div id="{chart_id}" class="chart"></div>
  <script>
    (function(){{
      var chart = LightweightCharts.createChart(document.getElementById('{chart_id}'), {{
        autoSize: true, height: 200,
        layout: {{ background: {{ color: '#1e1e2e' }}, textColor: '#cdd6f4' }},
        grid: {{ vertLines: {{ color: '#313244' }}, horzLines: {{ color: '#313244' }} }},
        timeScale: {{ borderColor: '#45475a' }},
      }});
      var series = chart.addCandlestickSeries({{
        upColor:'#26a69a', downColor:'#ef5350',
        borderUpColor:'#26a69a', borderDownColor:'#ef5350',
        wickUpColor:'#26a69a', wickDownColor:'#ef5350',
      }});
      series.setData({chart_json});
      chart.timeScale().fitContent();
    }})();
  </script>
</div>"""

    wti_card = ""
    if wti_data:
        c = color(wti_data["change_pct"])
        chart_json = json.dumps(wti_data["chart_data"])
        wti_card = f"""
<div class="card">
  <h2>WTI原油（USOIL）</h2>
  <div class="price">{wti_data['close']:.2f} USD
    <span class="change" style="color:{c}">{sign(wti_data['change'])} ({sign(wti_data['change_pct'])}%)</span>
  </div>
  <div class="meta">
    <span class="tag" style="background:{c}">{wti_data['candle']}</span>
    {wti_data['movement']}
  </div>
  <div class="ohlc">始値 {wti_data['open']:.2f} ／ 高値 {wti_data['high']:.2f} ／ 安値 {wti_data['low']:.2f}</div>
  <div id="wti_chart" class="chart"></div>
  <script>
    (function(){{
      var chart = LightweightCharts.createChart(document.getElementById('wti_chart'), {{
        autoSize: true, height: 200,
        layout: {{ background: {{ color: '#1e1e2e' }}, textColor: '#cdd6f4' }},
        grid: {{ vertLines: {{ color: '#313244' }}, horzLines: {{ color: '#313244' }} }},
        timeScale: {{ borderColor: '#45475a' }},
      }});
      var series = chart.addCandlestickSeries({{
        upColor:'#26a69a', downColor:'#ef5350',
        borderUpColor:'#26a69a', borderDownColor:'#ef5350',
        wickUpColor:'#26a69a', wickDownColor:'#ef5350',
      }});
      series.setData({chart_json});
      chart.timeScale().fitContent();
    }})();
  </script>
</div>"""

    news_html = ""
    for i, item in enumerate(news_items, 1):
        if item["url"]:
            news_html += f'<li><a href="{item["url"]}" target="_blank">{item["title"]}</a></li>\n'
        else:
            news_html += f'<li>{item["title"]}</li>\n'

    market_cards = "".join(card(name, data) for name, data in market_data.items())

    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>株式ブリーフィング {today_str}</title>
<script src="https://unpkg.com/lightweight-charts@4.2.0/dist/lightweight-charts.standalone.production.js"></script>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #11111b; color: #cdd6f4; font-family: -apple-system, sans-serif; padding: 12px; }}
h1 {{ font-size: 1.1rem; color: #89b4fa; margin-bottom: 4px; }}
.date {{ font-size: 0.85rem; color: #6c7086; margin-bottom: 16px; }}
.card {{ background: #1e1e2e; border-radius: 12px; padding: 16px; margin-bottom: 12px; }}
h2 {{ font-size: 1rem; color: #89dceb; margin-bottom: 8px; }}
.price {{ font-size: 1.6rem; font-weight: bold; }}
.change {{ font-size: 1rem; font-weight: normal; margin-left: 8px; }}
.meta {{ margin: 8px 0; font-size: 0.85rem; color: #a6adc8; }}
.tag {{ color: #fff; font-size: 0.75rem; padding: 2px 8px; border-radius: 4px; margin-right: 6px; }}
.ohlc {{ font-size: 0.78rem; color: #6c7086; margin-bottom: 8px; }}
.chart {{ width: 100%; margin-top: 8px; }}
.news {{ background: #1e1e2e; border-radius: 12px; padding: 16px; margin-bottom: 12px; }}
.news h2 {{ color: #89dceb; margin-bottom: 10px; }}
.news li {{ font-size: 0.88rem; margin-bottom: 10px; line-height: 1.5; list-style: none; padding-left: 1em; text-indent: -1em; }}
.news a {{ color: #89b4fa; text-decoration: none; }}
.footer {{ font-size: 0.75rem; color: #45475a; text-align: center; margin-top: 8px; }}
</style>
</head>
<body>
<h1>朝の株式ブリーフィング</h1>
<div class="date">{today_str} 更新</div>

{market_cards}
{wti_card}

<div class="news">
  <h2>市場関連ニュース</h2>
  <ul>{news_html}</ul>
</div>

<div class="footer">GitHub Actions により自動生成</div>
</body>
</html>"""


def send_email(subject, body):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    to_addr = os.environ["TO_EMAIL"]

    msg = MIMEMultipart()
    msg["From"] = smtp_user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, to_addr, msg.as_string())
    print(f"メール送信完了 → {to_addr}")


def main():
    today_str = datetime.now(JST).strftime("%Y年%m月%d日")
    github_user = os.environ.get("GITHUB_USER", "")
    github_repo = os.environ.get("GITHUB_REPO", "morning-briefing")
    pages_url = f"https://{github_user}.github.io/{github_repo}/" if github_user else ""

    market_data = {name: get_market_data(sym) for name, sym in TICKERS.items()}
    wti_data = get_market_data(WTI_TICKER)
    news_items = get_news()

    # HTMLファイル生成
    html = generate_html(market_data, wti_data, news_items, today_str)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("index.html を生成しました")

    body = build_email_body(market_data, wti_data, news_items, today_str, pages_url)
    subject = f"【朝の株式ブリーフィング】{today_str}"

    print(body)
    send_email(subject, body)


if __name__ == "__main__":
    main()
