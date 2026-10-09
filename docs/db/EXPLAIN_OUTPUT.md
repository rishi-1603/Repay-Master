# Database and cache evidence — Repay-Master (Day 7, 2026-10-08)

Repay-Master stores everything in SQLite (one file, `utils/auth.py` owns all access; there
is no Postgres, no ORM and no Redis in this project). That changes what Day 7 means here: the
questions worth answering are *"does a plan use an index"*, *"what does a connection cost"*,
and *"what happens when two writers meet"* — the last one because SQLite's single-writer rule
is a real constraint of the design, not a bug to be papered over.

Measured with `day7/scripts/rp_sqlite_probe.py` against a scratch database of **20,000 saved
scenarios for one user** (the app's own table). Raw transcripts:
`day7/raw/rp-sqlite-before.txt`, `day7/raw/rp-sqlite-after.txt`.

## 1. What was wrong, in three parts

**(a) Every connection ran two `CREATE TABLE IF NOT EXISTS` statements.** `_connect()` called
`_ensure_schema()` unconditionally, so all three DDL statements (two tables + the new index)
executed on *every* connect — including the connects that only read. The check is cheap for
SQLite but not free: **0.076 ms median per connect vs 0.020 ms for a bare
`sqlite3.connect`**, against 0.44 ms for an actual insert. The fix keeps the schema work
exactly once per process per database file (`_SCHEMA_ENSURED`), and — because the first
connect of a *new* file must still create the schema even after another path has been
ensured — keys the set on the file path. **After: 0.028 ms**, i.e. most of the DDL overhead
gone, and still safe for a brand-new database or a fresh process.

The subtle part is the check for a new file: `sqlite3.connect()` *creates* the file, so
"is this a new database?" has to be answered **before** connecting (`os.path.exists`), or a
second process would find an empty file and think the schema was already handled. The
comment in the code says this, and a test covers it.

**(b) The history list did a full table scan.** `SELECT ... WHERE username = ? ORDER BY id DESC`
planned as `SCAN saved_scenarios`: at 20k rows that is 54 ms and it grows linearly with every
other user's history, because SQLite has no way to jump to one user's rows. `_ensure_schema`
now creates `idx_saved_scenarios_username`, and the same query plans as
**`SEARCH saved_scenarios USING INDEX idx_saved_scenarios_username (username=?)`**.

Honesty check (the one that makes a plan assertion worth something): deleting the
`CREATE INDEX` line and re-running the new tests fails **2 of them** with
`plan was: SCAN saved_scenarios`. The assertions read `EXPLAIN QUERY PLAN` output, not a
comment.

**(c) `POST /api/history` read back the row it had just written by listing everything.**
After inserting, the endpoint called `get_saved_scenarios(username)` — which materialises
every scenario the user owns — and then searched that list in Python for the new id. On the
seeded database that is the 44 ms list, to return one row. There is now an owner-scoped
`get_scenario(username, scenario_id)` that reads the single row by primary key
(`SEARCH saved_scenarios USING INTEGER PRIMARY KEY (rowid=?)`), and a test
(`test_create_history_does_not_list_every_scenario` in
`backend/app/tests/test_sqlite_and_history_efficiency.py`) that asserts `get_saved_scenarios`
is **not** called during a POST — so the regression cannot come back
quietly.

## 2. Before and after

| Measurement (20k scenarios, one user) | Before | After |
|---|---:|---:|
| `_connect()` median, 200 calls | 0.076 ms | **0.028 ms** |
| bare `sqlite3.connect` (reference point) | 0.020 ms | 0.020 ms |
| history list plan | `SCAN saved_scenarios` | **`SEARCH … USING INDEX idx_saved_scenarios_username`** |
| POST read-back plan | list + Python scan | **`SEARCH … USING INTEGER PRIMARY KEY`** |
| insert one row | 0.44 ms | 0.35 ms |
| list 20,000 rows for one user | 54.24 ms | 44.18 ms |
| write-then-read consistency | rows 20002, read back OK | rows 20002, read back OK |

**Two numbers that did not improve much, and the reason.** The 20k-row list is still ~44 ms
and the index did not change that: the plan is now an index search, but the endpoint then runs
`json.loads` on every row's `params_json` and builds a dict per row, so the cost moved from
selection to (de)serialisation. The index fixed the *right* thing — the query no longer costs
more because other users have history — but the endpoint's cost is set by how many rows it
returns:

> **D7-2 (Low): `GET /api/history` returns every scenario a user has, unpaginated.** Not a
> regression — it was always like this — but it is why the per-row `json.loads` dominates,
> and it is the same shape as DevTrack's D7-1. Worth a `LIMIT`/page when the endpoint is next
> touched; a real user has tens of scenarios, not 20,000, so the urgency is low and this is
> registered as Low rather than fixed today.

## 3. SQLite's single writer: documented, not "solved"

With one connection holding a write transaction open, a second writer waits for the busy
timeout and then fails:

```
-- a second writer while the first holds a transaction --
  second writer after 502 ms: OperationalError: database is locked
```

(502 ms = the probe's `timeout=0.5`; the app's connections use the 5 s default.) The same
line appears in the before and after transcripts: **this is a property of SQLite, not a
defect introduced or removed by Day 7**, and the honest thing to do with it is write it down
rather than add a retry loop that would hide it. What it means in this app:

* Writes are single-row inserts and updates (save a scenario, mark nothing else), held open
  for microseconds, so two writers actually colliding is rare in normal use.
* The Streamlit UI and the FastAPI backend share one file, so a long-running write in either
  blocks the other. A `busy_timeout` exists (5 s default) and turns most of these into a short
  wait instead of an error.
* What would change the analysis: WAL mode (`PRAGMA journal_mode=WAL`, readers no longer block
  a writer), or moving to Postgres. Both are real options; both change deployment
  characteristics and belong to a decision with a reason, not to an index day. Not done here.

## 4. Cache

There is no cache layer in this project — no Redis, no memoisation of query results — so the
Day-7 bar "every Redis key has a TTL and an invalidation path" is satisfied by there being no
keys. Recorded explicitly because a reader comparing the three projects' Day-7 documents
should see the difference stated rather than inferred from silence. (`utils/finance.py`
computations are pure functions and cheap; the expensive thing was the history read, fixed in
§1.)

## 4a. What the file store means for persistence (feeds D2)

SQLite here is a file, so "the database" and "the filesystem" are the same problem.
`utils/auth.py` puts it at `data/app.db` inside the project directory:

* **In Docker, as documented, it survives restarts.** `docker-compose.yml` mounts the
  `repaymaster_data` volume at that path, and the Dockerfile comment says so; the history you
  save is still there after `docker compose restart`.
* **Anywhere without that volume, it does not.** On a platform that rebuilds the container
  filesystem on each deploy (the shape of D2 in the defect register), the file is created
  fresh and every saved scenario disappears — including the ones a user expected to keep.
  There is no migration path and no backup: SQLite has no server-side dump, so the only copy
  is the file. This is a deployment-shape limitation to state in the README rather than a bug
  to fix with code, and it is why the D2 entry stays open after Day 7.
* The measurable consequence for the rest of Day 7 is nil — all the timings in §2 are for a
  local file on the container's own disk — but it is the first thing a reader should know
  before treating this database as durable.

## 5. Tests and numbers

* `backend/app/tests/test_sqlite_and_history_efficiency.py` — **10 tests**: the index is used
  by the history query; the index exists on a brand-new database; the read-back uses the
  primary key; `_ensure_schema` runs once per path; connect cost stays under a bound; the
  write-then-read path including the on-disk file; `get_saved_scenarios` is not called during
  a POST; owner scoping; blank username.
* Deleting the index line fails 2 of them (kept as the honesty check in §1b).
* Full suite: `pytest app/tests` → **136 passed, 3 xfailed, 98%** (`--cov=app`), ruff clean.
  The three xfails are registered defects D1-7, D4-2a, D4-2b.
