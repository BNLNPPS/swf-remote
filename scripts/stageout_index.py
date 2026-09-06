#!/usr/bin/env python3
"""Index of the devcloud stage-out bucket, learned from the bucket's own events.

The gateway knows what is in the bucket by being told: S3 emits an
ObjectCreated event per report object to the epic-stageout-events queue,
this tool drains the queue into a local index, and the watch and the
nightly cross-check read the index instead of listing S3. Listing a
production-scale prefix every few minutes would cost about as much as
the reporting itself; a queue costs a dollar a month
(swf-epicprod docs/JOB_REPORTING.md).

Standard library plus the AWS CLI, which carries this host's account
credentials. No boto3, no venv, no web-tier coupling: the tool owns its
state and other things read it.

Modes:
  drain      receive events, record objects, delete the messages
  reconcile  authoritative count by listing, compared with the index
  summary    the state as JSON, for the Capcom tile and for a human
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time

BUCKET = os.environ.get("STAGEOUT_BUCKET", "epic-devcloud-stageout")
PREFIX = os.environ.get("STAGEOUT_PREFIX", "reports/")
QUEUE_URL = os.environ.get(
    "STAGEOUT_QUEUE_URL",
    "https://sqs.us-east-1.amazonaws.com/962718900486/epic-stageout-events")
DB_PATH = os.environ.get(
    "STAGEOUT_INDEX_DB", "/home/admin/data/stageout-index.sqlite")
# Objects per hour above which the watch calls it a runaway. A defect that
# posts in a loop inside one job is the unbounded risk the design names;
# the fleet itself is finite.
RATE_CEILING_PER_HOUR = int(os.environ.get("STAGEOUT_RATE_CEILING", "20000"))
# A job writing more than this many objects is looping, whatever the fleet
# total says.
PER_JOB_CEILING = int(os.environ.get("STAGEOUT_PER_JOB_CEILING", "50"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    key       TEXT PRIMARY KEY,
    size      INTEGER NOT NULL,
    etime     TEXT NOT NULL,
    subject   TEXT,
    seen_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS objects_seen ON objects (seen_at);
CREATE INDEX IF NOT EXISTS objects_subject ON objects (subject);
CREATE TABLE IF NOT EXISTS state (k TEXT PRIMARY KEY, v TEXT NOT NULL);
"""

# reports/<subject>/<sequence>.json — the subject is the PanDA job id once
# the payload carries it; anything else is recorded as it arrives.
SUBJECT_RE = re.compile(r"^reports/([^/]+)/")


def aws(*args, parse=True):
    """Run one AWS CLI call. A failure is raised with its stderr rather
    than swallowed: a silent indexer is worse than none."""
    proc = subprocess.run(("aws",) + args, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"aws {' '.join(args[:3])} failed ({proc.returncode}): "
            f"{proc.stderr.strip()[:400]}")
    if not parse:
        return proc.stdout
    out = proc.stdout.strip()
    return json.loads(out) if out else {}


def db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.executescript(SCHEMA)
    return conn


def set_state(conn, key, value):
    conn.execute("INSERT INTO state (k, v) VALUES (?, ?) "
                 "ON CONFLICT(k) DO UPDATE SET v = excluded.v",
                 (key, json.dumps(value)))


def get_state(conn, key, default=None):
    row = conn.execute("SELECT v FROM state WHERE k = ?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def subject_of(key):
    match = SUBJECT_RE.match(key)
    return match.group(1) if match else None


def drain(conn, max_batches=200):
    """Receive events and record their objects. Returns (recorded, seen).

    A message is deleted only after its rows are committed, so a crash
    repeats work rather than losing it; the key is the primary key, so a
    repeat is a no-op.
    """
    recorded = seen = 0
    for _ in range(max_batches):
        result = aws("sqs", "receive-message", "--queue-url", QUEUE_URL,
                     "--max-number-of-messages", "10",
                     "--wait-time-seconds", "1", "--output", "json")
        messages = result.get("Messages") or []
        if not messages:
            break
        handles = []
        for message in messages:
            seen += 1
            handles.append(message["ReceiptHandle"])
            try:
                body = json.loads(message["Body"])
            except (KeyError, ValueError) as exc:
                print(f"undecodable message body: {exc}", file=sys.stderr)
                continue
            # S3 sends one test event when the notification is configured.
            if body.get("Event") == "s3:TestEvent":
                continue
            for record in body.get("Records", []):
                obj = record.get("s3", {}).get("object", {})
                key = obj.get("key")
                if not key:
                    continue
                conn.execute(
                    "INSERT INTO objects (key, size, etime, subject, seen_at) "
                    "VALUES (?, ?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                    "size = excluded.size, etime = excluded.etime",
                    (key, int(obj.get("size") or 0),
                     record.get("eventTime", ""), subject_of(key), time.time()))
                recorded += 1
        conn.commit()
        for handle in handles:
            aws("sqs", "delete-message", "--queue-url", QUEUE_URL,
                "--receipt-handle", handle, parse=False)
    set_state(conn, "last_drain", {"at": time.time(), "recorded": recorded})
    conn.commit()
    return recorded, seen


def reconcile(conn):
    """The nightly cross-check: count the prefix authoritatively and
    compare with the index, then drop rows for objects that are gone.

    Listing once a night costs a fraction of a cent. Drift is the signal
    that events were missed or that something writes without telling us.
    """
    sizes = {}
    token = None
    while True:
        args = ["s3api", "list-objects-v2", "--bucket", BUCKET,
                "--prefix", PREFIX, "--output", "json"]
        if token:
            args += ["--starting-token", token]
        page = aws(*args)
        for item in page.get("Contents", []):
            sizes[item["Key"]] = int(item.get("Size") or 0)
        token = page.get("NextContinuationToken")
        if not (page.get("IsTruncated") and token):
            break
    keys = set(sizes)

    indexed = {row[0] for row in conn.execute("SELECT key FROM objects")}
    missing_from_index = keys - indexed          # events we never heard about
    gone_from_bucket = indexed - keys            # expired or swept

    for key in gone_from_bucket:
        conn.execute("DELETE FROM objects WHERE key = ?", (key,))
    # The listing carries the size, so an object recorded here is as
    # complete as one announced by an event, minus the event time.
    for key in missing_from_index:
        conn.execute(
            "INSERT INTO objects (key, size, etime, subject, seen_at) "
            "VALUES (?, ?, '', ?, ?) ON CONFLICT(key) DO NOTHING",
            (key, sizes[key], subject_of(key), time.time()))

    outcome = {"at": time.time(), "bucket_count": len(keys),
               "index_count": len(indexed),
               "unheard": len(missing_from_index),
               "pruned": len(gone_from_bucket)}
    set_state(conn, "last_reconcile", outcome)
    conn.commit()
    return outcome


def summary(conn):
    """The state other things read: totals, the last hour's rate against
    the ceiling, the busiest subject, and the freshness of both passes."""
    now = time.time()
    total = conn.execute("SELECT COUNT(*) FROM objects").fetchone()[0]
    hour = conn.execute("SELECT COUNT(*) FROM objects WHERE seen_at > ?",
                        (now - 3600,)).fetchone()[0]
    day = conn.execute("SELECT COUNT(*) FROM objects WHERE seen_at > ?",
                       (now - 86400,)).fetchone()[0]
    busiest = conn.execute(
        "SELECT subject, COUNT(*) c FROM objects WHERE seen_at > ? "
        "GROUP BY subject ORDER BY c DESC LIMIT 1", (now - 86400,)).fetchone()
    last_reconcile = get_state(conn, "last_reconcile", {})
    verdict, detail = "ok", ""
    if hour > RATE_CEILING_PER_HOUR:
        verdict = "alarm"
        detail = f"{hour} objects in the last hour, ceiling {RATE_CEILING_PER_HOUR}"
    elif busiest and busiest[1] > PER_JOB_CEILING:
        verdict = "warning"
        detail = (f"subject {busiest[0]} wrote {busiest[1]} objects today, "
                  f"per-job ceiling {PER_JOB_CEILING}")
    elif last_reconcile.get("unheard"):
        verdict = "warning"
        detail = (f"{last_reconcile['unheard']} objects in the bucket that no "
                  "event announced")
    return {"objects": total, "last_hour": hour, "last_day": day,
            "busiest_subject": busiest[0] if busiest else None,
            "busiest_count": busiest[1] if busiest else 0,
            "rate_ceiling": RATE_CEILING_PER_HOUR,
            "last_drain": get_state(conn, "last_drain", {}),
            "last_reconcile": last_reconcile,
            "verdict": verdict, "detail": detail}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("mode", choices=("drain", "reconcile", "summary"))
    args = parser.parse_args()
    conn = db()
    try:
        if args.mode == "drain":
            recorded, seen = drain(conn)
            print(f"drained {seen} messages, recorded {recorded} objects")
        elif args.mode == "reconcile":
            print(json.dumps(reconcile(conn), indent=2))
        else:
            print(json.dumps(summary(conn), indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
