"""sqlite index coverage, per-connection cost and write-then-read consistency (Day 7).

Repay-Master's store is a plain sqlite file that the Streamlit UI and the FastAPI
background both open directly, so there is no ORM and no migration tooling -- the
schema is created by `utils/auth.py:_connect()`. Everything here is measured against
that real path (the autouse `isolated_auth_db` fixture points `DB_PATH` at a temp file
per test, so the app's own database is never touched).

The three claims under test, all of which the Day-7 plan asked for by name:

1. **Index coverage on history lookups.** Every read is
   `WHERE username = ? ORDER BY id DESC`. Before this was added, the plan was
   `SCAN saved_scenarios` -- a full table scan of 20,000 rows (54 ms measured).
2. **Per-request connection handling.** `_connect()` runs the schema DDL on every
   call; the fix remembers which database files have been set up in this process
   (0.076 ms -> 0.028 ms per call), while still creating the schema for a file that
   has never been seen.
3. **Write-then-read consistency.** A scenario saved through the API is readable
   immediately afterwards, and it is on disk (not just in a connection's cache).
"""
import sqlite3

import pytest
import utils.auth as auth

from app.tests.conftest import auth_headers, register_and_login

# --------------------------------------------------------------------------
# index coverage
# --------------------------------------------------------------------------

def _plan(sql: str, params=()) -> str:
    conn = auth._connect()
    try:
        rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    finally:
        conn.close()
    return " | ".join(r[3] for r in rows)


def test_history_list_uses_the_username_index(client):
    token = register_and_login(client)
    for i in range(5):
        client.post("/history", json={"label": f"s{i}", "params": {"loan_amount": i}},
                    headers=auth_headers(token))

    plan = _plan("SELECT id, label, params_json, created_at FROM saved_scenarios "
                 "WHERE username = ? ORDER BY id DESC", ("alice",))
    assert "idx_saved_scenarios_username" in plan, (
        f"the history list is not using the username index; plan was: {plan}"
    )
    assert "SCAN" not in plan.split("USING")[0], f"still scanning: {plan}"


def test_index_exists_for_a_brand_new_database():
    """The index must be part of schema creation, not something applied by hand.

    `isolated_auth_db` has already pointed DB_PATH at a path that did not exist, so
    the first `_connect()` here is a genuine first-run.
    """
    auth._connect().close()
    conn = sqlite3.connect(auth.DB_PATH)
    try:
        names = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'")}
    finally:
        conn.close()
    assert "idx_saved_scenarios_username" in names, sorted(names)


def test_delete_still_uses_the_primary_key(client):
    token = register_and_login(client)
    row = client.post("/history", json={"label": "x", "params": {}}, headers=auth_headers(token)).json()
    plan = _plan("DELETE FROM saved_scenarios WHERE id = ? AND username = ?", (row["id"], "alice"))
    assert "PRIMARY KEY" in plan, plan


# --------------------------------------------------------------------------
# per-connection cost: schema created once per database file, not once per request
# --------------------------------------------------------------------------

def test_schema_is_created_once_per_database(monkeypatch):
    calls = []
    original = auth._ensure_schema

    def counting(conn):
        calls.append(auth.DB_PATH)
        return original(conn)

    monkeypatch.setattr(auth, "_ensure_schema", counting)
    monkeypatch.setattr(auth, "_SCHEMA_ENSURED", set())

    for _ in range(5):
        auth._connect().close()
    assert len(calls) == 1, (
        f"schema was created {len(calls)} times for 5 connections to one database; "
        "the DDL is pure per-request overhead after the first call"
    )

    # a different database file must still get its schema
    monkeypatch.setattr(auth, "DB_PATH", auth.DB_PATH + ".other")
    auth._connect().close()
    assert len(calls) == 2, "a database file that has never been seen must still be set up"


def test_connect_cost_is_close_to_a_bare_connect():
    """A regression guard with a loose bound: the DDL must not dominate the connect.

    Measured Day 7: 0.028 ms with the fix vs 0.076 ms before, against 0.020 ms for a
    bare `sqlite3.connect`. The bound is deliberately generous (machine-dependent).
    """
    import time

    auth._connect().close()                       # ensure the file exists and is set up
    t0 = time.perf_counter()
    for _ in range(200):
        auth._connect().close()
    with_fix = (time.perf_counter() - t0) / 200 * 1000

    t0 = time.perf_counter()
    for _ in range(200):
        sqlite3.connect(auth.DB_PATH).close()
    bare = (time.perf_counter() - t0) / 200 * 1000

    assert with_fix < bare + 0.5, f"_connect() took {with_fix:.3f} ms vs bare {bare:.3f} ms"


# --------------------------------------------------------------------------
# write-then-read consistency, and the lookup that used to read everything
# --------------------------------------------------------------------------

def test_saved_scenario_is_readable_immediately(client):
    token = register_and_login(client)
    created = client.post("/history", json={"label": "consistency",
                                            "params": {"loan_amount": 250000, "rate": 8.0}},
                          headers=auth_headers(token))
    assert created.status_code == 201, created.text

    listed = client.get("/history", headers=auth_headers(token)).json()
    assert [r["id"] for r in listed] == [created.json()["id"]]
    assert listed[0]["params"] == {"loan_amount": 250000, "rate": 8.0}

    # and it is on disk, not just in a connection's page cache
    conn = sqlite3.connect(auth.DB_PATH)
    try:
        row = conn.execute("SELECT label FROM saved_scenarios WHERE id = ?",
                           (created.json()["id"],)).fetchone()
    finally:
        conn.close()
    assert row == ("consistency",)


def test_create_history_does_not_list_every_scenario(client, monkeypatch):
    """`POST /history` must not read the whole table to return the row it just wrote.

    It used to call `get_saved_scenarios(username)` and scan the result in Python --
    fine with three rows, 54 ms with 20,000. Rather than assert on a timing, this
    replaces the list function with one that fails the test if it is called at all.
    """
    token = register_and_login(client)

    def forbidden(username):
        raise AssertionError("POST /history listed every scenario instead of looking up one row")

    monkeypatch.setattr(auth, "get_saved_scenarios", forbidden)
    resp = client.post("/history", json={"label": "one", "params": {"a": 1}}, headers=auth_headers(token))
    assert resp.status_code == 201, resp.text
    assert resp.json()["label"] == "one"


def test_get_scenario_is_owner_scoped(client):
    alice = register_and_login(client, username="alice-scope")
    register_and_login(client, username="bob-scope")   # the other user's token is not needed
    row = client.post("/history", json={"label": "alice's", "params": {}},
                      headers=auth_headers(alice)).json()

    assert auth.get_scenario(row["id"], "alice-scope")["label"] == "alice's"
    assert auth.get_scenario(row["id"], "bob-scope") is None, (
        "another user's scenario must not be readable by id -- ownership is enforced "
        "in the SQL, not in the caller"
    )


@pytest.mark.parametrize("username", ["", "  "])
def test_history_of_a_blank_username_is_empty(username):
    assert auth.get_saved_scenarios(username) == []
