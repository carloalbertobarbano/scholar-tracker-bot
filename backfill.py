"""Import citation counts from older copies of db.sqlite as dated snapshots.

Usage: python backfill.py TARGET_DB PROFILE_ID OLD_DB DATE [OLD_DB DATE ...]

Publications of PROFILE_ID are imported as-is. Publications from another
(previous) Scholar profile are matched to PROFILE_ID's publications by title;
when a title appears several times, pairs are assigned one-to-one, closest
citation count first. Unmatched entries are skipped. Existing snapshots in
TARGET_DB are never overwritten.
"""
import datetime as dt
import re
import sys

from sqlitedict import SqliteDict

from storage import History


def norm(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def match(old, current, profile):
    """old/current: {pub_id: {'title', 'citations'}} -> {current_id: citations}"""
    counts = {pid: v["citations"] for pid, v in old.items() if pid.startswith(profile + ":")}
    by_title = {}
    for pid, v in current.items():
        by_title.setdefault(norm(v["title"]), []).append(pid)
    pairs = []
    for opid, ov in old.items():
        if opid.startswith(profile + ":"):
            continue
        for cpid in by_title.get(norm(ov["title"]), []):
            # citation counts rarely drop much; a large drop means a different entry
            if ov["citations"] <= current[cpid]["citations"] + 2:
                pairs.append((abs(current[cpid]["citations"] - ov["citations"]), opid, cpid))
    used_old = set()
    for _, opid, cpid in sorted(pairs):
        if opid in used_old or cpid in counts:
            continue
        used_old.add(opid)
        counts[cpid] = old[opid]["citations"]
    skipped = [v["title"] for pid, v in old.items()
               if not pid.startswith(profile + ":") and pid not in used_old]
    return counts, skipped


def main(argv):
    if len(argv) < 4 or len(argv) % 2 != 0:
        sys.exit(__doc__)
    target, profile = argv[0], argv[1]
    with SqliteDict(target, flag="r") as db:
        current = {k: v for k, v in db.items() if k.startswith(profile + ":")}
    history = History(target)
    for old_db, date in zip(argv[2::2], argv[3::2]):
        with SqliteDict(old_db, flag="r") as old:
            old_items = dict(old.items())
        counts, skipped = match(old_items, current, profile)
        history.record_pubs(dt.date.fromisoformat(date), counts, overwrite=False)
        print(f"{date}: {len(counts)} publications imported from {old_db}")
        for t in skipped:
            print(f"    skipped (no match): {t[:80]}")
    history.close()


if __name__ == "__main__":
    main(sys.argv[1:])
