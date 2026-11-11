import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import tempfile
from pathlib import Path

import telebot
from telebot.types import InputMediaPhoto
from scholarly import scholarly
from scholarly.data_types import Author, AuthorSource
from sqlitedict import SqliteDict

import charts
import forecast
import messages
from storage import History

DB_PATH = './data/db.sqlite'
CHARTS_DIR = Path('./data/charts')


def parse_args():
    ap = argparse.ArgumentParser(description="Track Google Scholar citations and report to Telegram.")
    ap.add_argument('--summary', action='store_true',
                    help="send the graphical summary now, regardless of the schedule")
    ap.add_argument('--dry-run', action='store_true',
                    help="work on a copy of the database, print messages instead of sending them, "
                         "and write charts to --out")
    ap.add_argument('--out', default='./data/preview', help="chart directory for --dry-run")
    ap.add_argument('--theme', choices=['dark', 'light'],
                    help="chart theme (default: chart_theme in conf.json, else dark)")
    return ap.parse_args()


def fetch_author(author_id):
    author = Author(scholar_id=author_id, container_type="Author")
    author['filled'] = []
    author['source'] = AuthorSource.AUTHOR_PROFILE_PAGE
    return scholarly.fill(author)


def parse_year(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def summary_due(history, today, weekday):
    last = history.get_meta('last_summary')
    if last is None:
        return True
    last = dt.date.fromisoformat(last)
    if last == today:
        return False
    return today.weekday() == weekday or (today - last).days >= 7


class Sender:
    def __init__(self, config, dry_run):
        self.dry_run = dry_run
        self.chat_id = config['chat_id']
        self.bot = None if dry_run else telebot.TeleBot(token=config['token'], parse_mode="html")

    def text(self, text):
        for chunk in messages.split(text):
            if self.dry_run:
                print("----- message -----\n" + chunk)
            else:
                try:
                    self.bot.send_message(chat_id=self.chat_id, text=chunk,
                                          disable_web_page_preview=True)
                except telebot.apihelper.ApiTelegramException as e:
                    if "parse" not in str(e).lower():
                        raise
                    # never lose a report to a formatting problem: resend as plain text
                    print(f"Telegram rejected the formatting ({e}); sent as plain text")
                    plain = html.unescape(re.sub(r"<[^>]+>", "", chunk))
                    self.bot.send_message(chat_id=self.chat_id, text=plain, parse_mode="",
                                          disable_web_page_preview=True)

    def photos(self, paths):
        if not paths:
            return
        if self.dry_run:
            print("----- charts -----\n" + "\n".join(str(p) for p in paths))
            return
        files = [open(p, 'rb') for p in paths]
        try:
            self.bot.send_media_group(chat_id=self.chat_id,
                                      media=[InputMediaPhoto(f) for f in files])
        finally:
            for f in files:
                f.close()


def main():
    args = parse_args()
    os.makedirs('./data', exist_ok=True)
    config = json.load(open('./conf.json'))
    run_at = dt.datetime.now()
    today = run_at.date()

    db_path = DB_PATH
    charts_dir = CHARTS_DIR
    if args.dry_run:
        tmp = tempfile.mkdtemp(prefix='scholar-tracker-')
        db_path = os.path.join(tmp, 'db.sqlite')
        if os.path.exists(DB_PATH):
            shutil.copy(DB_PATH, db_path)
        charts_dir = Path(args.out)

    db = SqliteDict(db_path, autocommit=True)
    history = History(db_path)
    sender = Sender(config, args.dry_run)

    author = fetch_author(config['author_id'])
    print(f"Total citations: {author['citedby']}")

    pubs = {}
    for publication in author['publications']:
        pubs[publication['author_pub_id']] = {
            'title': publication['bib']['title'],
            'citations': publication['num_citations'],
            'year': parse_year(publication['bib'].get('pub_year')),
        }

    # Detect changes against the stored state (same table the original bot used).
    new_ids, deltas = [], {}
    for pid, p in pubs.items():
        stored_year = p['year'] if p['year'] is not None else 'N/A'
        entry = {'title': p['title'], 'citations': p['citations'], 'year': stored_year}
        if pid not in db:
            new_ids.append(pid)
            db[pid] = entry
        elif db[pid]['citations'] != p['citations']:
            deltas[pid] = p['citations'] - db[pid]['citations']
            db[pid] = entry

    history.record_run(run_at, author,
                       {p['author_pub_id']: p for p in author['publications']})

    report = forecast.build_report(
        today,
        {'citedby': author['citedby'], 'hindex': author.get('hindex'),
         'i10index': author.get('i10index'),
         'cites_per_year': author.get('cites_per_year', {})},
        pubs,
        history.pub_series(),
        history.author_series(),
    )
    by_id = {p.pub_id: p for p in report.papers}

    text = messages.daily(report,
                          [by_id[pid] for pid in new_ids],
                          [(by_id[pid], d) for pid, d in deltas.items()])
    if text:
        sender.text(text)

    if args.summary or summary_due(history, today, int(config.get('summary_weekday', 0))):
        sender.text(messages.summary(report))
        sender.photos(charts.render_all(report, charts_dir, args.theme or config.get('chart_theme', 'dark')))
        history.set_meta('last_summary', today.isoformat())

    db.commit()
    db.close()
    history.close()
    if args.dry_run:
        shutil.rmtree(os.path.dirname(db_path), ignore_errors=True)


if __name__ == '__main__':
    main()
