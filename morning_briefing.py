import yfinance as yf
import smtplib
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import pytz

JST = pytz.timezone("Asia/Tokyo")

TICKERS = {
    "S&P 500": "^GSPC",
    "ダウ平均": "^DJI",
    "ナスダック総合": "^IXIC",
}
WTI_TICKER = "CL=F"


def get_market_data(symbol):
    ticker = yf.Ticker(symbol)
    hist = ticker.history(period="5d")
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

    return {
        "open": o, "high": h, "low": l, "close": c,
        "change": change, "change_pct": change_pct,
        "candle": candle, "movement": movement,
        "date": hist.index[-1].strftime("%Y-%m-%d"),
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


def get_news():
    ticker = yf.Ticker("^GSPC")
    news_items = ticker.news or []
    results = []
    for item in news_items[:5]:
        content = item.get("content", {})
        title = content.get("title") or item.get("title", "")
        if title:
            results.append(title)
    return results


def build_email_body(market_data, wti_data, news_titles, today_str):
    sign = lambda x: f"+{x:.2f}" if x >= 0 else f"{x:.2f}"

    lines = [
        f"【朝の株式マーケットブリーフィング】{today_str}",
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
    if news_titles:
        for i, title in enumerate(news_titles, 1):
            lines.append(f"  {i}. {title}")
    else:
        lines.append("  ニュース取得失敗")

    lines += [
        "",
        "=" * 40,
        "本日の注目予定",
        "=" * 40,
        "  経済指標カレンダーは以下でご確認ください：",
        "  https://jp.investing.com/economic-calendar/",
        "",
        "-" * 40,
        "このメールはGitHub Actionsにより自動送信されました。",
    ]
    return "\n".join(lines)


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

    market_data = {name: get_market_data(sym) for name, sym in TICKERS.items()}
    wti_data = get_market_data(WTI_TICKER)
    news_titles = get_news()

    body = build_email_body(market_data, wti_data, news_titles, today_str)
    subject = f"【朝の株式ブリーフィング】{today_str}"

    print(body)
    send_email(subject, body)


if __name__ == "__main__":
    main()
