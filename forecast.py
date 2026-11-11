"""Trend estimation and year-end forecasts, built only from our own snapshots.

Model
-----
Citations arrive as a Poisson process whose rate changes exponentially over time:

    lambda(t) = rate * exp(g * t)        t in years, t = 0 is today

`rate` is the current citations/year and `g` the momentum (g > 0 accelerating,
g < 0 slowing down). The data are the citations gained between consecutive
snapshots; the expected gain over [a, b] is rate * integral_a^b exp(g t) dt.
Because every interval is weighted by where it sits in time, recent snapshots
pin down today's rate while older ones inform the momentum: the forecast bends
instead of extrapolating a straight line.

For each series we take the MAP estimate of g on a grid under a Gaussian prior
(the rate has a closed-form MLE given g). The prior keeps g sensible while the
history is short. For papers it follows the usual citation life cycle: new
papers ramp up, papers a few years old plateau, older ones slowly decline.

The profile total is modelled the same way. Its history combines Jan 1 totals
derived from Scholar's per-year counts (total today minus citations in that
year and later), the bot's own recorded totals, and, for recent dates not
covered by either, totals reconstructed from paper snapshots: per-paper counts
overlap (one citing paper can cite several of the author's papers), so paper
gains are divided by the current overlap ratio sum(paper counts) / total.
The profile fit uses the last AUTHOR_FIT_YEARS years plus the current one.

Ranges are 80% intervals from a negative-binomial approximation:
var = mean + OVERDISPERSION * mean^2, covering Poisson noise and uncertainty
in the rate.
"""
import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

DAYS_PER_YEAR = 365.25
G_GRID = np.linspace(-2.0, 2.0, 801)
OVERDISPERSION = 0.08
Z80 = 1.2816
PSEUDO_COUNT = 0.5          # keeps the rate > 0 for papers with no citations yet
TREND_THRESHOLD = 0.2       # |g| above this is labelled accelerating / slowing
INFORMATIVE_RATIO = 0.75    # posterior sd of g must shrink below this * prior sd
AUTHOR_FIT_YEARS = 1        # complete years before the current one used for the profile fit


def years_between(d0, d1):
    return (d1 - d0).days / DAYS_PER_YEAR


def _exposure(a, b, g):
    """integral_a^b exp(g t) dt, broadcasting over arrays."""
    a, b, g = np.broadcast_arrays(np.asarray(a, float), np.asarray(b, float), np.asarray(g, float))
    small = np.abs(g) < 1e-9
    g_safe = np.where(small, 1.0, g)
    return np.where(small, b - a, (np.exp(g_safe * b) - np.exp(g_safe * a)) / g_safe)


@dataclass
class RateFit:
    rate: float          # citations / year today
    growth: float        # g (MAP)
    growth_sd: float     # posterior sd of g
    prior_sd: float

    @property
    def informative(self):
        return self.growth_sd < INFORMATIVE_RATIO * self.prior_sd

    @property
    def trend(self):
        """'up' / 'flat' / 'down', or None when the history is too short to tell."""
        if not self.informative:
            return None
        if self.growth > TREND_THRESHOLD:
            return "up"
        if self.growth < -TREND_THRESHOLD:
            return "down"
        return "flat"

    def expected(self, a, b):
        return self.rate * float(_exposure(a, b, self.growth))


def fit_rate(intervals, prior_mean, prior_sd):
    """intervals: [(start, end, count)] with times in years relative to today."""
    iv = [(a, b, max(0, c)) for a, b, c in intervals if b - a > 1e-6]
    if not iv:
        return None
    a = np.array([x[0] for x in iv])[:, None]
    b = np.array([x[1] for x in iv])[:, None]
    c = np.array([x[2] for x in iv], float)[:, None]
    w = _exposure(a, b, G_GRID[None, :])                 # (intervals, grid)
    total = c.sum()
    w_sum = w.sum(axis=0)
    # profile log-likelihood of g (rate maximised out)
    loglik = (c * np.log(np.where(c > 0, w, 1.0))).sum(axis=0) - total * np.log(w_sum)
    logpost = loglik - 0.5 * ((G_GRID - prior_mean) / prior_sd) ** 2
    post = np.exp(logpost - logpost.max())
    post /= post.sum()
    i = int(np.argmax(logpost))
    g_mean = float((post * G_GRID).sum())
    g_sd = float(math.sqrt(max((post * (G_GRID - g_mean) ** 2).sum(), 0.0)))
    rate = (total + PSEUDO_COUNT) / float(w_sum[i])
    return RateFit(rate=rate, growth=float(G_GRID[i]), growth_sd=g_sd, prior_sd=prior_sd)


def growth_prior(pub_year, today):
    """Prior (mean, sd) for g given the paper's age."""
    if pub_year is None:
        return 0.0, 0.6
    age = today.year - pub_year + 0.5
    if age < 1:
        return 1.0, 0.8
    if age < 2:
        return 0.5, 0.6
    if age < 4:
        return 0.1, 0.5
    return -0.1, 0.4


def interval80(mean):
    sd = math.sqrt(mean + OVERDISPERSION * mean * mean)
    return max(0.0, mean - Z80 * sd), mean + Z80 * sd


def snapshot_intervals(series, today):
    rel = lambda d: years_between(today, d)
    return [(rel(d0), rel(d1), c1 - c0) for (d0, c0), (d1, c1) in zip(series, series[1:])]


@dataclass
class PaperForecast:
    pub_id: str
    title: str
    year: Optional[int]
    citations: int
    fit: Optional[RateFit]
    expected_gain: float = 0.0           # expected citations from today to Dec 31
    lo: float = 0.0                      # 80% range of the gain
    hi: float = 0.0
    recent_gain: Optional[int] = None    # citations gained since the reference snapshot
    recent_days: Optional[int] = None
    history: list = field(default_factory=list)

    @property
    def rate(self):
        return self.fit.rate if self.fit else 0.0

    @property
    def trend(self):
        return self.fit.trend if self.fit else None

    @property
    def year_end(self):
        return self.citations + self.expected_gain


@dataclass
class AuthorForecast:
    citedby: int
    hindex: int
    i10index: int
    history: list                 # [(date, citedby, estimated: bool)]
    fit: Optional[RateFit]
    expected_gain: float
    lo: float
    hi: float
    year_count: Optional[int]     # citations this calendar year, as reported in this run
    year_count_source: Optional[str]  # "recorded" (our Jan 1 snapshot) or "scholar"

    @property
    def total_year_end(self):
        return self.citedby + self.expected_gain

    def projection(self, today, year_end, steps=30):
        """[(date, mean, lo, hi)] from today to year end, for charts."""
        out = []
        span = (year_end - today).days
        for i in range(steps + 1):
            d = today + dt.timedelta(days=round(span * i / steps))
            m = self.fit.expected(0.0, years_between(today, d)) if self.fit else 0.0
            lo, hi = interval80(m)
            out.append((d, self.citedby + m, self.citedby + lo, self.citedby + hi))
        return out


@dataclass
class Report:
    today: dt.date
    year_end: dt.date
    author: AuthorForecast
    papers: list   # PaperForecast, sorted by current rate desc


def _paper_intervals(history, pub_year, today):
    out = snapshot_intervals(history, today)
    # For young papers the rise since publication is informative; the
    # exponential model is a poor fit over the full life of older papers.
    if history and pub_year is not None and pub_year >= today.year - 2:
        start = dt.date(pub_year, 7, 1)
        d0, c0 = history[0]
        if start < d0:
            out.append((years_between(today, start), years_between(today, d0), c0))
    return out


def _recent_gain(history, today, target_days=30, min_days=7, max_days=90):
    """Gain since the snapshot closest to `target_days` ago (within bounds)."""
    if len(history) < 2:
        return None, None
    now_c = history[-1][1]
    best = None
    for d, c in history[:-1]:
        age = (today - d).days
        if min_days <= age <= max_days and (best is None or abs(age - target_days) < abs(best[0] - target_days)):
            best = (age, c)
    if best is None:
        return None, None
    return now_c - best[1], best[0]


def estimate_author_history(author_actual, pub_history, current_ids, citedby_now, today):
    """Recorded profile totals, preceded by totals estimated from paper snapshots."""
    actual = [(d, c, False) for d, c in author_actual]
    anchor_date, anchor_total = (author_actual[0] if author_actual else (today, citedby_now))

    def paper_sum(d):
        s = 0
        for pid in current_ids:
            for sd, c in pub_history.get(pid, []):
                if sd == d:
                    s += c
                    break
        return s

    anchor_sum = paper_sum(anchor_date)
    if anchor_total <= 0 or anchor_sum <= 0:
        return actual
    overlap = anchor_sum / anchor_total
    dates = sorted({d for pid in current_ids for d, _ in pub_history.get(pid, []) if d < anchor_date})
    estimated = [(d, anchor_total - (anchor_sum - paper_sum(d)) / overlap, True) for d in dates]
    return estimated + actual


def _cites_per_year(author_now):
    """Scholar's per-year counts with int keys (JSON round-trips turn them into strings)."""
    return {int(k): v for k, v in (author_now.get("cites_per_year") or {}).items()}


def _scholar_year_anchors(author_now, today):
    """Jan 1 totals for every year in Scholar's per-year counts seen in this run.

    total(Jan 1 of Y) = total today - citations in Y and every later year.
    """
    cpy = _cites_per_year(author_now)
    total, out = author_now["citedby"], []
    for y in sorted((y for y in cpy if y <= today.year), reverse=True):
        total -= int(cpy[y])
        out.append((dt.date(y, 1, 1), total, True))
    return sorted(out, key=lambda p: p[0])


def _merge_scholar_anchors(a_hist, author_now, today, tolerance_days=7):
    """Combine our history with Scholar's yearly totals.

    Within the span Scholar's yearly totals cover (up to Jan 1 of the latest
    year) they replace totals we reconstructed from paper counts, which are
    rougher. Our own recorded snapshots always win over an anchor on a nearby
    date. After the last anchor our own snapshots carry the series.
    """
    anchors = _scholar_year_anchors(author_now, today)
    if not anchors:
        return a_hist
    last_anchor = anchors[-1][0]
    kept = [p for p in a_hist if not p[2] or p[0] > last_anchor]
    recorded = [d for d, _, est in kept if not est]
    anchors = [a for a in anchors
               if not any(abs((a[0] - d).days) <= tolerance_days for d in recorded)
               and a[0] < today]
    return sorted(kept + anchors, key=lambda p: p[0])


def _year_count(a_hist, author_now, today, tolerance_days=7):
    """Citations gained this calendar year.

    Measured from our own snapshot when one was recorded within a week of
    Jan 1; otherwise Scholar's current-year count observed in this run.
    Never interpolated: with no snapshot near Jan 1 that would be a guess.
    """
    jan1 = dt.date(today.year, 1, 1)
    near = [(abs((d - jan1).days), v) for d, v, est in a_hist
            if not est and abs((d - jan1).days) <= tolerance_days]
    if near:
        return round(author_now["citedby"] - min(near)[1]), "recorded"
    scholar = _cites_per_year(author_now).get(today.year)
    if scholar is not None:
        return int(scholar), "scholar"
    return None, None


def build_report(today, author_now, pubs, pub_history, author_actual):
    """
    author_now: dict with citedby, hindex, i10index, cites_per_year (this run)
    pubs: {pub_id: {'title', 'year', 'citations'}} (this run)
    pub_history: {pub_id: [(date, citations)]} including this run
    author_actual: [(date, citedby)] recorded profile totals, including this run
    """
    year_end = dt.date(today.year + 1, 1, 1)
    horizon = years_between(today, year_end)

    papers = []
    for pid, p in pubs.items():
        hist = pub_history.get(pid, [])
        mu, sd = growth_prior(p["year"], today)
        fit = fit_rate(_paper_intervals(hist, p["year"], today), mu, sd)
        gain, days = _recent_gain(hist, today)
        expected = fit.expected(0.0, horizon) if fit else 0.0
        lo, hi = interval80(expected)
        papers.append(PaperForecast(
            pub_id=pid, title=p["title"], year=p["year"], citations=p["citations"],
            fit=fit, expected_gain=expected, lo=lo, hi=hi,
            recent_gain=gain, recent_days=days, history=hist,
        ))
    papers.sort(key=lambda p: (p.rate, p.citations), reverse=True)

    a_hist = estimate_author_history(author_actual, pub_history, list(pubs),
                                     author_now["citedby"], today)
    a_hist = _merge_scholar_anchors(a_hist, author_now, today)
    # Fit on recent years only: one growth rate cannot describe a whole career
    # (fast early ramp-up, then a plateau). The chart still shows everything.
    fit_from = dt.date(today.year - AUTHOR_FIT_YEARS, 1, 1)
    a_fit = fit_rate(snapshot_intervals([(d, c) for d, c, _ in a_hist if d >= fit_from], today),
                     0.0, 0.5)
    a_gain = a_fit.expected(0.0, horizon) if a_fit else 0.0
    a_lo, a_hi = interval80(a_gain)
    year_count, year_source = _year_count(a_hist, author_now, today)
    author = AuthorForecast(
        citedby=author_now["citedby"], hindex=author_now.get("hindex"),
        i10index=author_now.get("i10index"), history=a_hist, fit=a_fit,
        expected_gain=a_gain, lo=a_lo, hi=a_hi,
        year_count=year_count, year_count_source=year_source,
    )
    return Report(today=today, year_end=year_end, author=author, papers=papers)
