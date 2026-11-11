"""Telegram message text (HTML parse mode).

Written to be skimmed on a phone: short lines, one idea per line, the key
number in bold, details tucked into an expandable quote.
"""
from html import escape

ARROWS = {"up": "↗", "flat": "→", "down": "↘", None: ""}
TREND_WORD = {"up": "accelerating", "flat": "steady", "down": "slowing", None: None}
TELEGRAM_LIMIT = 4096
TOP_MOVERS = 5
LIST_MAX = 15


def _title(p, n=70):
    t = " ".join(p.title.split())
    t = t if len(t) <= n else t[: n - 1].rstrip(" ,:;-") + "…"
    return escape(t, quote=False)


def _signed(n):
    return f"+{n}" if n > 0 else f"−{abs(n)}" if n < 0 else "0"


def _year_end(report):
    a = report.author
    return (f"about <b>{a.total_year_end:,.0f}</b> "
            f"<i>(likely {a.citedby + a.lo:,.0f}–{a.citedby + a.hi:,.0f})</i>")


def daily(report, new_pubs, changed):
    """new_pubs: [PaperForecast]; changed: [(PaperForecast, delta)]. None when nothing happened."""
    if not new_pubs and not changed:
        return None
    a = report.author
    net = sum(d for _, d in changed)
    lines = []
    if changed:
        noun = "citation" if abs(net) == 1 else "citations"
        lines.append(f"🔔 <b>{_signed(net)} new {noun}</b>" if net > 0
                     else "🔔 <b>Citation update</b>")
        lines.append(f"Total now <b>{a.citedby:,}</b> · heading for ~{a.total_year_end:,.0f} by Dec 31")
        lines.append("")
        for p, d in sorted(changed, key=lambda t: t[1], reverse=True):
            lines.append(f"<b>{_signed(d)}</b>  {_title(p)}")
    if new_pubs:
        if lines:
            lines.append("")
        lines.append("🆕 <b>New on your profile</b>")
        for p in new_pubs:
            year = f" · {p.year}" if p.year else ""
            lines.append(f"{_title(p)}{year}")
    return "\n".join(lines)


def summary(report):
    a = report.author
    head = [
        "📊 <b>Weekly citation report</b>",
        f"<i>{report.today:%A, %d %B %Y}</i>",
        "",
        f"<b>{a.citedby:,}</b> citations · h-index <b>{a.hindex}</b> · i10 <b>{a.i10index}</b>",
        "",
    ]
    if a.fit:
        trend = TREND_WORD[a.fit.trend]
        head.append(f"📈 <b>Pace:</b> {a.fit.rate:,.0f} a year" + (f", {trend}" if trend else ""))
    head.append(f"🎯 <b>By Dec 31:</b> {_year_end(report)}")
    if a.year_count is not None:
        src = " <i>(Google Scholar)</i>" if a.year_count_source == "scholar" else ""
        head.append(f"🗓 <b>{report.today.year} so far:</b> {a.year_count:,} citations{src}")

    movers = sorted((p for p in report.papers if p.expected_gain >= 0.5),
                    key=lambda p: p.expected_gain, reverse=True)[:TOP_MOVERS]
    body = []
    if movers:
        body += ["", "🔥 <b>Top movers</b>"]
        for i, p in enumerate(movers, 1):
            details = [f"{p.citations:,} → ~{p.year_end:,.0f} by Dec 31"]
            if p.recent_gain:
                details.append(f"+{p.recent_gain} in the last {p.recent_days} days")
            if p.trend in ("up", "down"):
                details.append(f"{TREND_WORD[p.trend]} {ARROWS[p.trend]}")
            body += ["", f"<b>{i}. {_title(p)}</b>", " · ".join(details)]

    foot = ["", "<i>“Likely” is an 80% range. Trends firm up after a few weeks of daily checks.</i>"]

    # All papers by pace, folded away; trimmed so the message fits one Telegram message.
    ranked = [p for p in report.papers if p.fit and p.citations > 0 and p.rate >= 0.5]
    rows = [f"<b>{p.rate:.0f}</b>/yr{(' ' + ARROWS[p.trend]) if p.trend else ''} · {_title(p, 60)}"
            for p in ranked[:LIST_MAX]]
    if len(ranked) > LIST_MAX:
        rows.append(f"<i>…and {len(ranked) - LIST_MAX} more</i>")
    fixed = "\n".join(head + body + foot)
    while rows:
        quote = ("\n\n<blockquote expandable>📚 <b>All papers by pace</b>\n"
                 + "\n".join(rows) + "</blockquote>")
        if len(fixed) + len(quote) <= TELEGRAM_LIMIT:
            break
        rows.pop()
    quote = quote if rows else ""
    return "\n".join(head + body) + quote + "\n" + "\n".join(foot)


def split(text, limit=TELEGRAM_LIMIT):
    """Split on line boundaries to respect Telegram's message size limit."""
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit and cur:
            chunks.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        chunks.append(cur)
    return chunks
