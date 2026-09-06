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
  sweep      read failed jobs' reports, keep what is useful, delete them
  guard      nightly: is this an explosion, and pull the plug if so
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

# The nightly guard's ceilings. Expected production is of the order of
# 100,000 objects a day at a few kilobytes each; these are the levels at
# which the traffic stops being production and starts being a defect.
REPORTING_USER = os.environ.get("STAGEOUT_REPORTING_USER", "epic-job-reporter")
OBJECT_SOFT_CEILING_PER_DAY = int(
    os.environ.get("STAGEOUT_OBJECT_SOFT", "500000"))
OBJECT_HARD_CEILING_PER_DAY = int(
    os.environ.get("STAGEOUT_OBJECT_HARD", "1000000"))
BYTES_SOFT_CEILING_PER_DAY = int(os.environ.get("STAGEOUT_BYTES_SOFT",
                                                str(5 * 10 ** 9)))
BYTES_HARD_CEILING_PER_DAY = int(os.environ.get("STAGEOUT_BYTES_HARD",
                                                str(50 * 10 ** 9)))
# A day that is this many times the recent norm is an explosion whatever
# the absolute ceilings say; the floor keeps a quiet week from tripping it.
RELATIVE_MULTIPLE = int(os.environ.get("STAGEOUT_RELATIVE_MULTIPLE", "20"))
RELATIVE_FLOOR = int(os.environ.get("STAGEOUT_RELATIVE_FLOOR", "5000"))

# The sweep. Objects are read only for jobs PanDA says failed, and only a
# bounded number per failure signature: a storm says one thing many
# thousands of times, and reading it one object at a time buys nothing.
# Which jobs failed is PanDA's knowledge, on the far side of the
# perimeter, so the sweep asks the monitor's MCP relay rather than
# guessing from the reports themselves — a job that dies after writing a
# healthy report says nothing about its own death.
SWEEP_CREDENTIAL = os.environ.get(
    "STAGEOUT_SWEEP_ENV", "/home/admin/.epic-sweep-mcp.env")
SWEEP_LOOKBACK_DAYS = int(os.environ.get("STAGEOUT_SWEEP_DAYS", "2"))
SWEEP_KEEP_PER_SIGNATURE = int(os.environ.get("STAGEOUT_SWEEP_KEEP", "5"))
SWEEP_MAX_READS = int(os.environ.get("STAGEOUT_SWEEP_MAX_READS", "200"))
# A job's objects are left alone until it has been over for this long, so
# the sweep never races a job that is still writing.
SWEEP_MIN_AGE_SECONDS = int(os.environ.get("STAGEOUT_SWEEP_MIN_AGE", "1800"))

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
CREATE TABLE IF NOT EXISTS reports (
    pandaid    INTEGER PRIMARY KEY,
    jeditaskid INTEGER,
    site       TEXT,
    endtime    TEXT,
    report     TEXT NOT NULL,
    objects    INTEGER NOT NULL,
    swept_at   REAL NOT NULL,
    flushed_at REAL
);
CREATE INDEX IF NOT EXISTS reports_flushed ON reports (flushed_at);
CREATE TABLE IF NOT EXISTS daily (
    day       TEXT PRIMARY KEY,
    objects   INTEGER NOT NULL,
    bytes     INTEGER NOT NULL,
    at        REAL NOT NULL
);
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


def guard(conn, arm=True):
    """The nightly guard: does the traffic look like an explosion, and
    pull the plug if it does.

    The signal is the index, not the bill: objects and bytes are what
    boom first and the invoice is their lagging shadow. Two absolute
    ceilings and one relative one, because a ceiling set against today's
    expectation ages badly, and a sudden multiple of the recent norm is
    the shape of a runaway whatever the norm was.

    The plug is the reporting key. Disabling it stops jobs already
    running, since a running job keeps the environment it started with
    and the payload treats a failed write as ordinary (swf-epicprod
    docs/JOB_REPORTING.md). Only that key is touched: the sweep and
    stage-out keys survive, so reading and log stage-out continue.
    """
    now = time.time()
    day_objects, day_bytes = conn.execute(
        "SELECT COUNT(*), COALESCE(SUM(size), 0) FROM objects "
        "WHERE seen_at > ?", (now - 86400,)).fetchone()
    # The trailing norm, excluding the last day, over whatever history
    # the index holds. Expiry keeps that to about a week.
    prior_days = conn.execute(
        "SELECT COUNT(*) FROM objects WHERE seen_at <= ? AND seen_at > ?",
        (now - 86400, now - 7 * 86400)).fetchone()[0]
    norm_per_day = prior_days / 6.0 if prior_days else 0.0

    breaches = []
    if day_objects > OBJECT_HARD_CEILING_PER_DAY:
        breaches.append(f"{day_objects:,} objects in 24 hours, hard ceiling "
                        f"{OBJECT_HARD_CEILING_PER_DAY:,}")
    if day_bytes > BYTES_HARD_CEILING_PER_DAY:
        breaches.append(f"{day_bytes / 1e9:.1f} GB written in 24 hours, hard "
                        f"ceiling {BYTES_HARD_CEILING_PER_DAY / 1e9:.0f} GB")
    if (norm_per_day >= RELATIVE_FLOOR
            and day_objects > norm_per_day * RELATIVE_MULTIPLE):
        breaches.append(
            f"{day_objects:,} objects in 24 hours against a recent norm of "
            f"{norm_per_day:,.0f} a day, over {RELATIVE_MULTIPLE}x")

    warnings = []
    if not breaches:
        if day_objects > OBJECT_SOFT_CEILING_PER_DAY:
            warnings.append(f"{day_objects:,} objects in 24 hours, expected "
                            f"under {OBJECT_SOFT_CEILING_PER_DAY:,}")
        if day_bytes > BYTES_SOFT_CEILING_PER_DAY:
            warnings.append(f"{day_bytes / 1e9:.1f} GB in 24 hours, expected "
                            f"under {BYTES_SOFT_CEILING_PER_DAY / 1e9:.0f} GB")

    stopped = key_status() == "Inactive"
    if breaches and arm and not stopped:
        disable_reporting_key()
        stopped = True

    # The day's totals are kept forever, so growth outlives the objects.
    today = time.strftime("%Y-%m-%d", time.gmtime(now - 43200))
    conn.execute(
        "INSERT INTO daily (day, objects, bytes, at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(day) DO UPDATE SET objects = excluded.objects, "
        "bytes = excluded.bytes, at = excluded.at",
        (today, day_objects, day_bytes, now))
    history = [
        {"day": row[0], "objects": row[1], "bytes": row[2]}
        for row in conn.execute(
            "SELECT day, objects, bytes FROM daily ORDER BY day DESC LIMIT 14")]
    this_week = sum(r["objects"] for r in history[:7])
    last_week = sum(r["objects"] for r in history[7:14])
    growth = (round((this_week - last_week) / last_week, 2)
              if last_week else None)

    outcome = {"at": now, "day_objects": day_objects,
               "day_bytes": day_bytes,
               "history": history[:14],
               "week_over_week": growth,
               "norm_objects_per_day": round(norm_per_day),
               "breaches": breaches, "warnings": warnings,
               "reporting_key_stopped": stopped}
    set_state(conn, "last_guard", outcome)
    conn.commit()
    return outcome


def _sweep_credential():
    """The relay URL and bearer token, from the mode-600 environment file."""
    values = {}
    with open(SWEEP_CREDENTIAL) as handle:
        for line in handle:
            if "=" in line and not line.startswith("#"):
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    url, token = values.get("SWEEP_MCP_URL"), values.get("SWEEP_MCP_TOKEN")
    if not url or not token:
        raise RuntimeError(f"{SWEEP_CREDENTIAL} lacks the relay URL or token")
    return url, token


def mcp_call(tool, arguments, timeout=120):
    """One tool call on the swf-monitor MCP relay, as the service account.

    The relay is how this side of the perimeter asks PanDA anything; it
    is the same path a person's browser takes, under a token rather than
    a session.
    """
    import urllib.request

    url, token = _sweep_credential()
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                       "params": {"name": tool, "arguments": arguments}})
    request = urllib.request.Request(
        url, data=body.encode(), method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode())
    if "error" in payload:
        raise RuntimeError(f"{tool} failed: {payload['error']}")
    text = payload["result"]["content"][0]["text"]
    return json.loads(text)


def jobs_by_status(status, days):
    """PanDA ids in the window with that terminal status, and the
    attributes the signature and the record need. Paged through the
    relay's id cursor.

    Status is read positively, never inferred from absence: a job missing
    from the failed list may have finished, may still be running, or may
    lie outside the window, and those are not the same thing.
    """
    found = {}
    before_id = None
    for _ in range(20):
        arguments = {"status": status, "days": days, "limit": 500}
        if before_id:
            arguments["before_id"] = before_id
        page = mcp_call("panda_list_jobs", arguments)
        rows = page.get("jobs") or []
        if not rows:
            break
        for row in rows:
            found[int(row["pandaid"])] = {
                "jeditaskid": row.get("jeditaskid"),
                "site": row.get("computingsite"),
                "endtime": row.get("endtime") or row.get("modificationtime")}
        before_id = min(int(r["pandaid"]) for r in rows)
        if len(rows) < 500:
            break
    return found


def delete_objects(keys):
    """Delete in batches, the API's own unit, rather than one call each."""
    deleted = 0
    for start in range(0, len(keys), 100):
        batch = keys[start:start + 100]
        payload = json.dumps(
            {"Objects": [{"Key": k} for k in batch], "Quiet": True})
        aws("s3api", "delete-objects", "--bucket", BUCKET,
            "--delete", payload, parse=False)
        deleted += len(batch)
    return deleted


def sweep(conn):
    """Read the objects of failed jobs, keep what is useful, delete them.

    Selective by design: a bounded number of jobs per failure signature
    are read and stored, and the rest of that signature's objects are
    deleted unread. The signature is the task and site until the payload
    digest is available for it; a storm concentrates in both.

    A finished job's objects are deleted the moment this pass learns the
    job finished. Their usefulness ended at that verdict, and leaving
    them to the seven-day rule would keep a week of dead weight in the
    bucket for nothing. Expiry stays as the backstop for jobs this pass
    could not resolve: still running, or outside the window.
    """
    now = time.time()
    swept_already = {row[0] for row in conn.execute(
        "SELECT pandaid FROM reports")}
    # Candidate subjects: numeric ids, quiet long enough to be over.
    candidates = {}
    for subject, count, newest in conn.execute(
            "SELECT subject, COUNT(*), MAX(seen_at) FROM objects "
            "WHERE subject IS NOT NULL GROUP BY subject"):
        if not str(subject).isdigit() or int(subject) in swept_already:
            continue
        if now - newest < SWEEP_MIN_AGE_SECONDS:
            continue
        candidates[int(subject)] = count
    if not candidates:
        outcome = {"at": now, "candidates": 0, "read": 0, "stored": 0,
                   "deleted_unread": 0, "objects_deleted": 0}
        set_state(conn, "last_sweep", outcome)
        conn.commit()
        return outcome

    failed = jobs_by_status("failed", SWEEP_LOOKBACK_DAYS)
    targets = {pid: failed[pid] for pid in candidates if pid in failed}

    # Finished jobs: nothing to learn, so their objects go now rather
    # than sitting out the week.
    finished = jobs_by_status("finished", SWEEP_LOOKBACK_DAYS)
    finished_deleted = finished_objects = 0
    for pandaid in candidates:
        if pandaid in targets or pandaid not in finished:
            continue
        keys = [row[0] for row in conn.execute(
            "SELECT key FROM objects WHERE subject = ?", (str(pandaid),))]
        if not keys:
            continue
        finished_objects += delete_objects(keys)
        conn.execute("DELETE FROM objects WHERE subject = ?", (str(pandaid),))
        finished_deleted += 1
    conn.commit()

    groups = {}
    for pandaid, attrs in targets.items():
        groups.setdefault(
            (attrs["jeditaskid"], attrs["site"]), []).append(pandaid)

    read = stored = unread = objects_deleted = 0
    for signature, members in groups.items():
        members.sort()
        for position, pandaid in enumerate(members):
            keys = [row[0] for row in conn.execute(
                "SELECT key FROM objects WHERE subject = ? ORDER BY key",
                (str(pandaid),))]
            if not keys:
                continue
            keep = (position < SWEEP_KEEP_PER_SIGNATURE
                    and read < SWEEP_MAX_READS)
            if keep:
                # The last object is the most complete account the job
                # managed to write before it died.
                try:
                    text = aws("s3", "cp", f"s3://{BUCKET}/{keys[-1]}", "-",
                               parse=False)
                    report = json.loads(text)
                    read += 1
                except (RuntimeError, ValueError) as exc:
                    print(f"unreadable report for {pandaid}: {exc}",
                          file=sys.stderr)
                    continue
                attrs = targets[pandaid]
                conn.execute(
                    "INSERT INTO reports (pandaid, jeditaskid, site, endtime, "
                    "report, objects, swept_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(pandaid) DO UPDATE SET report = excluded.report",
                    (pandaid, attrs["jeditaskid"], attrs["site"],
                     attrs["endtime"], json.dumps(report), len(keys), now))
                stored += 1
            else:
                unread += 1
            objects_deleted += delete_objects(keys)
            conn.execute("DELETE FROM objects WHERE subject = ?",
                         (str(pandaid),))
            conn.commit()

    outcome = {"at": now, "candidates": len(candidates),
               "failed_of_those": len(targets), "signatures": len(groups),
               "read": read, "stored": stored, "deleted_unread": unread,
               "objects_deleted": objects_deleted,
               "finished_jobs_cleared": finished_deleted,
               "finished_objects_deleted": finished_objects,
               "unresolved": len(candidates) - len(targets) - finished_deleted,
               "pending_flush": conn.execute(
                   "SELECT COUNT(*) FROM reports WHERE flushed_at IS NULL"
               ).fetchone()[0]}
    set_state(conn, "last_sweep", outcome)
    conn.commit()
    return outcome


def reporting_key_id():
    """The reporting user's access key id, from IAM rather than from the
    credential file, so the guard acts on what is actually enabled."""
    keys = aws("iam", "list-access-keys", "--user-name", REPORTING_USER,
               "--output", "json").get("AccessKeyMetadata", [])
    return keys[0]["AccessKeyId"] if keys else None


def key_status():
    try:
        keys = aws("iam", "list-access-keys", "--user-name", REPORTING_USER,
                   "--output", "json").get("AccessKeyMetadata", [])
        return keys[0]["Status"] if keys else "Missing"
    except RuntimeError as exc:
        print(f"key status unreadable: {exc}", file=sys.stderr)
        return "Unknown"


def disable_reporting_key():
    """Pull the plug. Reversible with one command, named in the notice."""
    key_id = reporting_key_id()
    if not key_id:
        raise RuntimeError(f"no access key found for {REPORTING_USER}")
    aws("iam", "update-access-key", "--user-name", REPORTING_USER,
        "--access-key-id", key_id, "--status", "Inactive", parse=False)
    print(f"DISABLED reporting key {key_id}; re-enable with: "
          f"aws iam update-access-key --user-name {REPORTING_USER} "
          f"--access-key-id {key_id} --status Active", file=sys.stderr)
    return key_id


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
    last_guard = get_state(conn, "last_guard", {})
    if last_guard.get("reporting_key_stopped"):
        verdict, detail = "alarm", (
            "the reporting key is disabled: "
            + "; ".join(last_guard.get("breaches") or ["stopped by the guard"]))
    return {"objects": total, "last_hour": hour, "last_day": day,
            "guard": last_guard,
            "busiest_subject": busiest[0] if busiest else None,
            "busiest_count": busiest[1] if busiest else 0,
            "rate_ceiling": RATE_CEILING_PER_HOUR,
            "last_drain": get_state(conn, "last_drain", {}),
            "last_reconcile": last_reconcile,
            "verdict": verdict, "detail": detail}


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "mode",
        choices=("drain", "reconcile", "sweep", "guard", "summary"))
    parser.add_argument("--no-arm", action="store_true",
                        help="report a breach without disabling the key")
    args = parser.parse_args()
    conn = db()
    try:
        if args.mode == "drain":
            recorded, seen = drain(conn)
            print(f"drained {seen} messages, recorded {recorded} objects")
        elif args.mode == "reconcile":
            print(json.dumps(reconcile(conn), indent=2))
        elif args.mode == "sweep":
            print(json.dumps(sweep(conn), indent=2))
        elif args.mode == "guard":
            print(json.dumps(guard(conn, arm=not args.no_arm), indent=2))
        else:
            print(json.dumps(summary(conn), indent=2))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
