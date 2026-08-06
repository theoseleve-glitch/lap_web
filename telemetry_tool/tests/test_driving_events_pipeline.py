"""Driving events — schema, persistence, stage wiring and real-data acceptance."""
import inspect
import os
import pathlib
from collections import Counter
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest


def test_driving_events_table_exists_with_the_expected_columns(test_db):
    cur = test_db.execute("SELECT * FROM driving_events LIMIT 0")
    cols = {d[0] for d in cur.description}

    for c in (
        "session_id", "lap_number", "corner_id", "event_type",
        "s_norm_start", "s_norm_end",
        "magnitude", "magnitude_unit",
        "time_cost_s", "validity", "reason",
        "n_samples_in_window", "evidence_json",
    ):
        assert c in cols, f"{c} missing from driving_events"


def test_driving_events_has_a_unique_key_so_reprocess_does_not_double(test_db):
    """Without this, every reprocess doubles the table."""
    row = dict(
        session_id="s1", lap_number=1, corner_id=1, event_type="over_slowing",
        s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4, magnitude_unit="m/s",
        time_cost_s=0.31, validity="measured", reason=None,
        anchor_tier="driver_best_session", anchor_reason=None,
        n_samples_in_window=42, evidence_json="{}",
    )
    cols = ", ".join(row)
    binds = ", ".join(f":{k}" for k in row)
    sql = f"INSERT OR REPLACE INTO driving_events ({cols}) VALUES ({binds})"

    test_db.execute(sql, row)
    test_db.execute(sql, row)
    test_db.commit()

    n = test_db.execute(
        "SELECT count(*) FROM driving_events WHERE session_id='s1'"
    ).fetchone()[0]
    assert n == 1, "reprocess duplicated the row -- unique key missing"


# ══════════════════════════════════════════════════════════════════
# Final review, CRITICAL 3 + deferred minor 5 — the persistence call site
# ══════════════════════════════════════════════════════════════════
#
# All three call sites are `if not events: return` plus a swallow, so a
# silent zero-write was both the likeliest failure and the only one nothing
# covered. And on the s15 path the swallow was worse than useless:
# `run_persist_to_db` is ONE transaction, so a failed write on PostgreSQL
# aborts it and the later COMMIT silently becomes a ROLLBACK -- taking laps,
# GPS traces, scores, theoretical data and corner metrics with it.


def _one_event():
    import driving_events as de

    return de.DrivingEvent(
        event_type="over_slowing", lap_number=3, corner_id=2,
        s_norm_start=0.25, s_norm_end=0.35, magnitude=1.4,
        magnitude_unit="m/s", time_cost_s=0.31,
        validity=de.VALIDITY_MEASURED, reason=None,
        anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
        n_samples_in_window=42,
        evidence={"apex_speed_mps": 12.0, "reference_apex_speed_mps": 13.4},
    )


def test_the_persist_call_site_actually_writes_a_row(seeded_db):
    """End to end through the shipped call site, not through the repo
    function it happens to call. A renamed summary key, a reordered guard or
    a swallowed bind error all produce a silent zero-write here."""
    from pipeline.stages import s15_persist

    s15_persist._persist_driving_events(
        seeded_db, "s1", {"driving_events": [_one_event()]})
    seeded_db.commit()

    rows = seeded_db.execute(
        "SELECT * FROM driving_events WHERE session_id='s1'").fetchall()
    assert len(rows) == 1, "the shipped call site wrote nothing"
    assert rows[0]["event_type"] == "over_slowing"
    assert rows[0]["lap_number"] == 3
    assert rows[0]["magnitude"] == pytest.approx(1.4)


class _AbortsLikePostgres:
    """sqlite3 connection wrapped in PostgreSQL's transaction semantics.

    WHY A FAKE AND NOT JUST sqlite3: SQLite does NOT abort a transaction when
    a statement fails -- measured, not assumed: a failed INSERT followed by
    COMMIT still commits everything else. So this whole defect is invisible on
    SQLite and a test written directly against `seeded_db` PASSES AGAINST THE
    BROKEN CODE. The first draft of this test did exactly that and was thrown
    away.

    Modelled on psycopg2's documented behaviour, which is what production
    runs (web/db_pg.py, no autocommit):
      * any statement error puts the connection in the aborted state;
      * every later statement raises InFailedSqlTransaction until the block
        ends -- EXCEPT `ROLLBACK TO SAVEPOINT`, which is precisely the escape
        hatch the fix uses;
      * `COMMIT` inside an aborted block is a SILENT ROLLBACK, which is how
        an entire session's data disappears behind one WARNING line.

    The fake is proved to reproduce the defect by
    `test_the_postgres_abort_model_reproduces_the_total_loss` below; without
    that proof this test would have no teeth either.
    """

    ABORT_MSG = ("current transaction is aborted, commands ignored until "
                 "end of transaction block")

    def __init__(self, real):
        self._c = real
        self.aborted = False
        self.silently_rolled_back = False

    def execute(self, sql, params=None):
        head = " ".join(str(sql).strip().split()).upper()
        if head.startswith("ROLLBACK TO SAVEPOINT"):
            self.aborted = False
            return self._raw(sql, params)
        if self.aborted:
            raise RuntimeError(self.ABORT_MSG)
        return self._raw(sql, params)

    def _raw(self, sql, params):
        try:
            return (self._c.execute(sql) if params is None
                    else self._c.execute(sql, params))
        except Exception:
            self.aborted = True
            raise

    def commit(self):
        if self.aborted:
            self._c.rollback()
            self.aborted = False
            self.silently_rolled_back = True
            return
        self._c.commit()

    def rollback(self):
        self._c.rollback()
        self.aborted = False


def _session_mid_transaction(seeded_db):
    """A connection carrying uncommitted session data, with `driving_events`
    missing -- i.e. code deployed before `alembic upgrade` ran 086."""
    seeded_db.execute("DROP TABLE driving_events")
    seeded_db.commit()
    conn = _AbortsLikePostgres(seeded_db)
    conn.execute("INSERT INTO laps (session_id, lap_number, lap_time_s, "
                 "is_valid) VALUES ('s1', 99, 61.0, 1)")
    return conn


def _surviving_laps(seeded_db):
    return seeded_db.execute(
        "SELECT count(*) FROM laps WHERE session_id='s1' AND lap_number=99"
    ).fetchone()[0]


def test_the_postgres_abort_model_reproduces_the_total_loss(seeded_db):
    """Guards the FIXTURE, not the fix. Every assertion in the next test is
    worthless unless a naive swallow really does lose the session against
    this connection -- so prove it here, with the swallow written out."""
    from web.repos.events_repo import insert_driving_events

    conn = _session_mid_transaction(seeded_db)

    try:                                   # the shape s15 used to have
        insert_driving_events(conn, "s1", [_one_event()])
    except Exception:
        pass                               # "logged a warning, continued"
    conn.commit()

    assert conn.silently_rolled_back, (
        "the model did not abort the transaction, so it does not reproduce "
        "the defect and the paired test below proves nothing")
    assert _surviving_laps(seeded_db) == 0, (
        "the fixture does not exhibit the total loss")


def test_a_failed_driving_events_write_does_not_discard_the_session(seeded_db):
    """CRITICAL 3: the table is missing, the write fails, and everything ELSE
    the same transaction was carrying must still commit."""
    from pipeline.stages import s15_persist

    conn = _session_mid_transaction(seeded_db)

    s15_persist._persist_driving_events(
        conn, "s1", {"driving_events": [_one_event()]})
    conn.commit()

    assert not conn.silently_rolled_back, (
        "COMMIT became a silent ROLLBACK -- the failed driving-events write "
        "poisoned the outer transaction")
    assert _surviving_laps(seeded_db) == 1, (
        "a failed driving-events write discarded the rest of the session: "
        "laps, GPS traces, scores, theoretical data and corner metrics all "
        "go with it, behind one WARNING line naming only driving events")


def test_without_isolation_the_failure_is_raised_rather_than_swallowed(seeded_db):
    """If the SAVEPOINT itself cannot be taken there is nothing to contain
    the failure, and swallowing it is the dangerous branch. A loud failure
    that rolls the transaction back is strictly better than a silent one
    that discards the session and reports success.

    ⚠ THE EXCEPTION'S IDENTITY IS THE ASSERTION, and this test was worthless
    without it. `pytest.raises(Exception)` alone passes with the
    `if not sp_taken: raise` branch INVERTED **and** with it DELETED -- both
    mutations still raise, just from a different place: the rollback attempt
    fails with `sqlite3.OperationalError: no such savepoint`, and a bare
    `raises(Exception)` cannot tell that apart from the write's own failure.
    That is the branch a third writer is most likely to invert, at the cost
    of the whole session, so it needs the tightest assertion here rather
    than the loosest.
    """
    from pipeline.stages import s15_persist

    conn = _session_mid_transaction(seeded_db)
    real_execute = conn.execute

    def no_savepoints(sql, params=None):
        if " ".join(str(sql).split()).upper().startswith("SAVEPOINT"):
            raise RuntimeError("savepoints unavailable")
        return real_execute(sql, params)

    conn.execute = no_savepoints

    with pytest.raises(Exception) as ei:
        s15_persist._persist_driving_events(
            conn, "s1", {"driving_events": [_one_event()]})

    msg = str(ei.value)
    assert "no such table: driving_events" in msg, (
        f"the exception that reached the caller is {msg!r} -- that is not "
        f"the WRITE failing, it is the rollback attempt failing afterwards. "
        f"The `if not sp_taken: raise` branch is not doing the work; a "
        f"swallow here would look identical to the caller.")
    assert "savepoint" not in msg.lower(), msg


def test_the_anchor_provenance_survives_the_round_trip(seeded_db):
    """IMPORTANT 1a: spec SS5.1's `anchor_tier` must reach BOTH read surfaces,
    not just the dataclass. Neither surface used to carry it, so a consumer
    could not tell an `envelope_under_use` percentage backed by the fitted
    session envelope from one backed by the driver's own best -- two
    different baselines, numerically indistinguishable (median 97.7 vs
    94.7 on the real fixture)."""
    import driving_events as de
    from pipeline.stages import s15_persist
    from web.repos import events_repo

    ev = de.DrivingEvent(
        event_type="envelope_under_use", lap_number=4, corner_id=7,
        s_norm_start=0.5, s_norm_end=0.6, magnitude=94.7,
        magnitude_unit=de.MAGNITUDE_UNIT_PCT, time_cost_s=None,
        validity=de.VALIDITY_MEASURED, reason=None, n_samples_in_window=30,
        anchor_tier=de.ANCHOR_SESSION_ENVELOPE_DEFAULT_P2,
        anchor_reason=None, evidence={"grip_anchor_pct": 94.7},
    )
    costed = de.DrivingEvent(
        event_type="over_slowing", lap_number=4, corner_id=7,
        s_norm_start=0.5, s_norm_end=0.6, magnitude=1.4,
        magnitude_unit=de.MAGNITUDE_UNIT_MPS, time_cost_s=0.31,
        validity=de.VALIDITY_MEASURED, reason=None, n_samples_in_window=30,
        anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION, anchor_reason=None,
        evidence={"apex_speed_mps": 12.0},
    )
    s15_persist._persist_driving_events(
        seeded_db, "s1", {"driving_events": [ev, costed]})
    seeded_db.commit()

    stored = seeded_db.execute(
        "SELECT event_type, anchor_tier, anchor_reason FROM driving_events "
        "WHERE session_id='s1' ORDER BY event_type").fetchall()
    assert [(r["event_type"], r["anchor_tier"]) for r in stored] == [
        ("envelope_under_use", de.ANCHOR_SESSION_ENVELOPE_DEFAULT_P2),
        ("over_slowing", de.ANCHOR_DRIVER_BEST_SESSION),
    ]

    ranked = events_repo.get_ranked_events(seeded_db, "s1")
    assert ranked and ranked[0]["anchor_tier"] == de.ANCHOR_DRIVER_BEST_SESSION

    corners = events_repo.get_corner_consistency(seeded_db, "s1")
    assert corners and corners[0]["anchor_tiers"] == [
        de.ANCHOR_DRIVER_BEST_SESSION], (
        "the aggregate is quoted to a driver too, so it must say what it "
        "was measured against")


def test_late_throttle_ships_no_time_cost_and_no_quotable_magnitude(seeded_db):
    """2026-08-06 ruling. IMPORTANT 4 marked the cost `context` and shipped it
    anyway; the ruling took it away entirely, because asking a consumer not to
    attribute a number you handed them is a weaker guarantee than not handing
    it over.

    The magnitude is a SEPARATE axis and is still unquotable standalone --
    `re_braking` shows the two do not follow from each other: no cost, but a
    perfectly quotable deceleration.
    """
    import driving_events as de
    from pipeline.stages import s15_persist
    from web.repos import events_repo

    def _ev(event_type, unit, cost, lap):
        return de.DrivingEvent(
            event_type=event_type, lap_number=lap, corner_id=lap,
            s_norm_start=0.1, s_norm_end=0.2, magnitude=5.0,
            magnitude_unit=unit, time_cost_s=cost,
            validity=de.VALIDITY_MEASURED, reason=None, n_samples_in_window=30,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION, anchor_reason=None,
            evidence={"x": 1},
        )

    assert de.TIME_COST_ATTRIBUTION["late_throttle"] == de.ATTRIBUTION_NO_COST
    assert de.MAGNITUDE_STANDALONE_QUOTABLE["late_throttle"] is False
    assert de.MAGNITUDE_STANDALONE_QUOTABLE["re_braking"] is True, (
        "the two axes must stay independent -- re_braking has no cost and a "
        "perfectly quotable magnitude")

    s15_persist._persist_driving_events(seeded_db, "s1", {"driving_events": [
        _ev("late_throttle", de.MAGNITUDE_UNIT_M, None, 1),
        _ev("over_slowing", de.MAGNITUDE_UNIT_MPS, 0.31, 2),
    ]})
    seeded_db.commit()

    ranked = events_repo.get_ranked_events(seeded_db, "s1")
    assert [e["event_type"] for e in ranked] == ["over_slowing"], (
        "a costless late_throttle must not occupy a ranked slot on its own")

    os_ = ranked[0]
    assert os_["time_cost_attribution"] == de.ATTRIBUTION_ATTRIBUTABLE
    assert os_["magnitude_is_standalone_quotable"] is True


def test_the_payload_does_not_ship_the_evidence_twice(seeded_db):
    """Deferred minor 3: the row carried `evidence` (parsed) AND
    `evidence_json` (the same bytes as a string). Dropping the raw copy
    halves the response and the per-row memory the ranked read holds while
    deduping."""
    import driving_events as de
    from pipeline.stages import s15_persist
    from web.repos import events_repo

    s15_persist._persist_driving_events(seeded_db, "s1", {"driving_events": [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=1,
            s_norm_start=0.1, s_norm_end=0.2, magnitude=1.4,
            magnitude_unit=de.MAGNITUDE_UNIT_MPS, time_cost_s=0.31,
            validity=de.VALIDITY_MEASURED, reason=None,
            n_samples_in_window=30,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION, anchor_reason=None,
            evidence={"apex_speed_mps": 12.0}),
    ]})
    seeded_db.commit()

    row = events_repo.get_ranked_events(seeded_db, "s1")[0]
    assert row["evidence"] == {"apex_speed_mps": 12.0}
    assert "evidence_json" not in row


# ══════════════════════════════════════════════════════════════════
# Final review, IMPORTANT 2 — the capability record is no longer discarded
# ══════════════════════════════════════════════════════════════════


def test_a_failed_anchor_stage_is_no_longer_indistinguishable_from_a_clean_session():
    """THE defect: when `10d2_grip_anchor` fails, three of four detectors go
    `insufficient` and the API returns `{"events": [], "available": false}`
    with zero consistency rows -- byte-identical to a clean session with
    nothing to fix. The capability record is the only thing that separates
    them, and it was computed and thrown away."""
    from web.repos import events_repo

    clean = {"over_slowing": "not_triggered", "late_throttle": "not_triggered",
             "re_braking": "not_triggered",
             "envelope_under_use": "not_triggered"}
    broken = {"over_slowing": "insufficient", "late_throttle": "insufficient",
              "re_braking": "detected", "envelope_under_use": "insufficient"}

    assert clean != broken, "the two states must not be representable alike"

    # Both would produce the SAME ranked/consistency output; only this
    # record tells them apart, so it has to survive to a consumer.
    import inspect
    src = inspect.getsource(events_repo.get_driving_events_capability)
    assert "analysis_json" in src


def test_the_capability_record_survives_persistence_and_reaches_the_reader(seeded_db):
    from web.repos import events_repo
    from web.repos.analysis_repo import insert_analysis_json

    cap = {"over_slowing": "detected", "late_throttle": "insufficient",
           "re_braking": "not_triggered", "envelope_under_use": "insufficient"}
    insert_analysis_json(seeded_db, "s1", {"driving_events_capability": cap})
    seeded_db.commit()

    assert events_repo.get_driving_events_capability(seeded_db, "s1") == cap
    # A session with no blob at all is `{}`, never None, and never a guess.
    assert events_repo.get_driving_events_capability(seeded_db, "s2") == {}


def test_both_analysis_blob_writers_carry_the_capability_record():
    """There are TWO blob writers -- the celery/PG path and the sync upload
    path -- and a record persisted by only one of them is absent on half the
    product. Asserted structurally because both functions want a full
    pipeline result to run."""
    import inspect
    from tasks import pipeline_tasks
    from web.routes import sessions_v2

    for fn in (pipeline_tasks._build_analysis_blob,
               sessions_v2._persist_analysis_json):
        src = inspect.getsource(fn)
        assert 'blob["driving_events_capability"]' in src, fn.__name__
        # `isinstance(..., dict)`, not truthiness: an EMPTY capability record
        # means the stage did not run, which is its own fact and must not
        # read the same as "the key was never added".
        assert "isinstance(dec, dict)" in src, fn.__name__


# ══════════════════════════════════════════════════════════════════
# Deferred minor 4 — the read surfaces are bounded, and provably so
# ══════════════════════════════════════════════════════════════════


def test_the_ranked_query_is_bounded_and_still_yields_limit_distinct_keys(test_db):
    """The bound must do BOTH jobs: cap the fetch, and still return `limit`
    DISTINCT problems.

    The pathological case moved with the 2026-08-06 ruling. It used to be
    "two cost-bearing rows per key eat two slots"; now every key carries all
    FOUR event types, only one of which has a cost, so the join amplifies
    rows 4x while the ranking must still come out exact.
    """
    import driving_events as de
    from web.repos import events_repo

    evs = []
    for lap in range(1, 21):
        evs.append(de.DrivingEvent(
            event_type="over_slowing", lap_number=lap, corner_id=1,
            s_norm_start=0.1, s_norm_end=0.2, magnitude=5.0,
            magnitude_unit=de.MAGNITUDE_UNIT_MPS,
            time_cost_s=1.0 - lap * 0.01,
            validity=de.VALIDITY_MEASURED, reason=None, n_samples_in_window=30,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION, anchor_reason=None,
            evidence={"x": 1}))
        for etype, unit in (("late_throttle", de.MAGNITUDE_UNIT_M),
                            ("re_braking", de.MAGNITUDE_UNIT_MPS2),
                            ("envelope_under_use", de.MAGNITUDE_UNIT_PCT)):
            evs.append(de.DrivingEvent(
                event_type=etype, lap_number=lap, corner_id=1,
                s_norm_start=0.1, s_norm_end=0.2, magnitude=7.0,
                magnitude_unit=unit, time_cost_s=None,
                validity=de.VALIDITY_MEASURED, reason=None,
                n_samples_in_window=30,
                anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION, anchor_reason=None,
                evidence={"x": 1}))
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    for limit in (1, 5, 10, 20):
        got = events_repo.get_ranked_events(test_db, "s1", limit=limit)
        assert len(got) == limit, (
            f"asked for {limit} distinct problems, got {len(got)} -- the SQL "
            f"bound truncated before the dedupe could run")
        keys = {(e["lap_number"], e["corner_id"]) for e in got}
        assert len(keys) == limit, "duplicate (lap, corner) survived"
        assert all(e["event_type"] == "over_slowing" for e in got), (
            "only a cost-bearing detector may define the ranking")
        for e in got:
            also = {a["event_type"] for a in e["evidence"]["also_fired"]}
            assert also == {"late_throttle", "re_braking",
                            "envelope_under_use"}, also
        assert [e["time_cost_s"] for e in got] == sorted(
            (e["time_cost_s"] for e in got), reverse=True)
    assert got[0]["time_cost_s"] == pytest.approx(0.99)


def test_a_key_with_several_cost_bearing_rows_still_consumes_one_slot(test_db):
    """Defence for the arithmetic the removed assertion used to police.

    If a future detector starts emitting a cost, two rows for one corner-lap
    become cost-bearing. The subquery GROUPs BY the key, so that must still
    be ONE ranked entry consuming ONE slot -- not two, and not a duplicated
    facet list. Reproduced before the GROUP BY landed: the key came back
    twice and the facet list carried each companion several times.
    """
    import driving_events as de
    from web.repos import events_repo

    evs = []
    for lap in (1, 2, 3):
        for etype, unit, cost in (
                ("over_slowing", de.MAGNITUDE_UNIT_MPS, 0.9 - lap * 0.1),
                ("late_throttle", de.MAGNITUDE_UNIT_M, 0.9 - lap * 0.1),
                ("re_braking", de.MAGNITUDE_UNIT_MPS2, None)):
            evs.append(de.DrivingEvent(
                event_type=etype, lap_number=lap, corner_id=2,
                s_norm_start=0.1, s_norm_end=0.2, magnitude=3.0,
                magnitude_unit=unit, time_cost_s=cost,
                validity=de.VALIDITY_MEASURED, reason=None,
                n_samples_in_window=30,
                anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION, anchor_reason=None,
                evidence={"x": 1}))
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    got = events_repo.get_ranked_events(test_db, "s1", limit=3)
    assert len(got) == 3
    assert len({(e["lap_number"], e["corner_id"]) for e in got}) == 3
    for e in got:
        also = [a["event_type"] for a in e["evidence"]["also_fired"]]
        assert sorted(also) == ["late_throttle", "re_braking"], (
            f"facets duplicated by the join: {also}")


def test_the_consistency_surface_has_its_own_hard_cap():
    """It aggregates rather than slices, so it cannot borrow the ranked
    query's caller-scaled bound. Truncation there is a WRONG median, not a
    short list, so hitting the cap must be logged."""
    import inspect
    from web.repos import events_repo

    assert events_repo._CONSISTENCY_ROW_CAP > 0
    src = inspect.getsource(events_repo.get_corner_consistency)
    assert "_CONSISTENCY_ROW_CAP" in src
    assert "logger.warning" in src


# ── NEW-1: the same hazard one door down, opened by OUR migration 085 ────
#
# `_persist_corner_metrics` had the identical bare swallow, and it is
# reachable in this branch's own deploy window: 085 adds four columns that
# `INSERT_CORNER_METRIC` names unconditionally. Proven on a real PostgreSQL
# 16 with 085's columns dropped -- `run_persist_to_db` returned None and left
# sessions / laps / gps_traces / score_details / condition_phases /
# driving_events ALL at zero.


_CM_SUMMARY = {"per_lap_corner_metrics": [
    {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 12.0,
     "grip_anchor_tier": "driver_best_session", "grip_anchor_pct": 94.0},
]}
"""The key `insert_corner_metrics` actually reads. A summary keyed `corners`
returns 0 WITHOUT touching the database, so a fixture built that way never
reaches the INSERT and the paired tests below would prove nothing -- caught
by the fixture-guard test."""


def _corner_metrics_session(seeded_db):
    """A connection carrying uncommitted session data whose corner-metrics
    write is guaranteed to fail -- the 085-missing shape, reproduced by
    removing the table the INSERT names."""
    seeded_db.execute("DROP TABLE corner_metrics")
    seeded_db.commit()
    conn = _AbortsLikePostgres(seeded_db)
    conn.execute("INSERT INTO laps (session_id, lap_number, lap_time_s, "
                 "is_valid) VALUES ('s1', 98, 61.0, 1)")
    return conn


def _surviving_lap_98(seeded_db):
    return seeded_db.execute(
        "SELECT count(*) FROM laps WHERE session_id='s1' AND lap_number=98"
    ).fetchone()[0]


def test_the_corner_metrics_abort_model_reproduces_the_total_loss(seeded_db):
    """Guards the FIXTURE. The paired test below is worthless unless a bare
    swallow really does lose the session here, so prove it with the swallow
    written out."""
    conn = _corner_metrics_session(seeded_db)

    try:                                    # the shape s15 used to have
        from web.models import insert_corner_metrics
        insert_corner_metrics(conn, "s1", _CM_SUMMARY)
    except Exception:
        pass                                # "logged a warning, continued"
    conn.commit()

    assert conn.silently_rolled_back, (
        "the model did not abort, so it does not reproduce the defect")
    assert _surviving_lap_98(seeded_db) == 0


def test_a_failed_corner_metrics_write_does_not_discard_the_session(seeded_db):
    """NEW-1: 085's deploy window must not cost the whole session either."""
    from pipeline.stages import s15_persist

    conn = _corner_metrics_session(seeded_db)

    s15_persist._persist_corner_metrics(conn, "s1", _CM_SUMMARY)
    conn.commit()

    assert not conn.silently_rolled_back, (
        "COMMIT became a silent ROLLBACK -- the failed corner-metrics write "
        "poisoned the outer transaction, exactly as 086's did before it was "
        "guarded")
    assert _surviving_lap_98(seeded_db) == 1, (
        "a failed corner-metrics write discarded the rest of the session")


def test_corner_metrics_without_isolation_raises_rather_than_swallowing(seeded_db):
    """Same contract as the driving-events guard: no savepoint, no pretending
    the failure was contained. The exception's IDENTITY is the assertion --
    see the sibling test for why `pytest.raises(Exception)` alone passes
    against both a deleted and an inverted branch.
    """
    from pipeline.stages import s15_persist

    conn = _corner_metrics_session(seeded_db)
    real_execute = conn.execute

    def no_savepoints(sql, params=None):
        if " ".join(str(sql).split()).upper().startswith("SAVEPOINT"):
            raise RuntimeError("savepoints unavailable")
        return real_execute(sql, params)

    conn.execute = no_savepoints

    with pytest.raises(Exception) as ei:
        s15_persist._persist_corner_metrics(conn, "s1", _CM_SUMMARY)

    msg = str(ei.value)
    assert "no such table: corner_metrics" in msg, (
        f"the exception that reached the caller is {msg!r} -- that is not "
        f"the WRITE failing, it is the rollback attempt failing afterwards. "
        f"The `if not sp_taken: raise` branch is not doing the work; a "
        f"swallow here would look identical to the caller.")
    assert "savepoint" not in msg.lower(), msg


def test_both_child_writers_share_one_savepoint_implementation():
    """Two hand-rolled copies of a guard whose non-obvious branch costs the
    whole session when copied wrong is not a pattern worth repeating. A third
    writer must reuse this, not re-derive it."""
    import inspect
    from pipeline.stages import s15_persist

    for fn in (s15_persist._persist_corner_metrics,
               s15_persist._persist_driving_events):
        src = inspect.getsource(fn)
        assert "_write_in_savepoint" in src, fn.__name__
        # Strip the docstring before looking for hand-rolled SQL: both
        # functions legitimately DESCRIBE the savepoint in prose.
        body = src.split('"""')[-1]
        assert "conn.execute(f\"SAVEPOINT" not in body, (
            f"{fn.__name__} hand-rolls savepoint SQL instead of reusing the "
            f"shared helper")
        assert "ROLLBACK TO SAVEPOINT" not in body, fn.__name__


def test_an_empty_event_list_writes_nothing_and_does_not_raise(seeded_db):
    from pipeline.stages import s15_persist

    s15_persist._persist_driving_events(seeded_db, "s1", {})
    s15_persist._persist_driving_events(seeded_db, "s1", {"driving_events": []})
    seeded_db.commit()
    assert seeded_db.execute(
        "SELECT count(*) FROM driving_events").fetchone()[0] == 0


def test_driving_events_is_registered_for_retention_and_gdpr():
    """Data that cannot be purged or exported is a compliance defect."""
    from tasks import retention_tasks
    import inspect
    from tasks import gdpr_tasks

    assert "driving_events" in retention_tasks._RAW_DATA_TABLES
    assert "driving_events" in inspect.getsource(gdpr_tasks)


def test_driving_events_is_registered_in_every_delete_cascade_registry():
    """A table missing from ANY registry leaves orphaned rows on SQLite
    (the FK there has no ON DELETE CASCADE) and under-counts every backend's
    delete-impact dry-run preview.

    There are FOUR, not the three the plan named -- the final review's
    IMPORTANT 3 found `track_repo.delete_track_cascade` missed. It lists ~20
    session-child tables including `corner_metrics`; `driving_events` sat
    right next to it and was absent, so deleting a track left event rows
    behind permanently on SQLite.
    """
    import inspect
    from web.repos.delete_cascade import CASCADE_CONFIG
    from web.repos import driver_repo, track_repo

    assert "driving_events" in CASCADE_CONFIG["session"]["children"]
    assert "driving_events" in inspect.getsource(driver_repo.delete_driver_cascade)
    # NOTE this source-text assertion is weak on its own -- it passes on a
    # mere COMMENT mentioning the table (verified while bite-checking: the
    # tuple was deleted and this still went green). The executed test below
    # is the one with teeth; this one only names the fourth registry.
    assert "driving_events" in inspect.getsource(track_repo.delete_track_cascade)


def test_deleting_a_track_removes_its_driving_events(seeded_db):
    """Executed, not asserted structurally: the registry entry has to be in
    the loop that actually runs, with the right join column."""
    from web.repos import track_repo
    from pipeline.stages import s15_persist

    s15_persist._persist_driving_events(
        seeded_db, "s1", {"driving_events": [_one_event()]})
    seeded_db.commit()
    assert seeded_db.execute(
        "SELECT count(*) FROM driving_events").fetchone()[0] == 1

    track_repo.delete_track_cascade(seeded_db, "t1")
    seeded_db.commit()

    assert seeded_db.execute(
        "SELECT count(*) FROM driving_events").fetchone()[0] == 0, (
        "driving_events rows outlived the track that owned them -- SQLite's "
        "mirror has no ON DELETE CASCADE, so nothing else will collect them")


def test_stage_returns_events_and_a_capability_record():
    from pipeline.stages import s10d3_driving_events

    n = 400
    d = np.linspace(0.0, 1200.0, n)
    def lap(v):
        return pd.DataFrame({
            "Distance (m)": d, "distance_norm": d / 1200.0,
            "Speed (m/s)": np.full(n, v),
            "Lateral acceleration (G) *calc": np.full(n, 0.9),
            "Longitudinal acceleration (G) *calc": np.zeros(n),
        })

    corners = [{"corner_id": 1, "s_start": 300.0, "s_end": 400.0}]
    metrics = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0,
         "corner_time_s": 10.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 70.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 12.5,
         "corner_time_s": 8.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 99.0},
    ]

    out = s10d3_driving_events.run_driving_events(
        metrics, corners, {1: lap(10.0), 2: lap(12.5)},
    )

    assert "events" in out and "capability" in out
    assert set(out["capability"]) == {
        "over_slowing", "late_throttle", "re_braking", "envelope_under_use"}
    # lap 1 was slower than the reference, so something must be said about it
    assert any(e.lap_number == 1 for e in out["events"])


def test_a_corner_with_no_reference_at_all_still_lets_reference_free_detectors_evaluate():
    """Fix round 1 regression: a corner where NO admissible lap ever produced
    a finite apex_speed_mps, corner_time_s or throttle_onset_m (a total
    reference gap) used to skip building ANY window for that corner --
    starving `re_braking`/`envelope_under_use`, which never read `reference`
    at all, of windows they had every field for. The reviewer's own example:
    a strong clean post-apex decel run plus a low grip_anchor_pct, but no
    apex speed / corner time / throttle onset anywhere.

    Both halves in the SAME scenario, per the fix request:
      (1) re_braking / envelope_under_use must NOT read "insufficient" --
          their own required fields (a_long_mps2+apex_idx, grip_anchor_pct)
          are present, so they must evaluate and fire here.
      (2) over_slowing / late_throttle must STILL read "insufficient", not
          "not_triggered" -- there is genuinely nothing to compare against,
          and that must not be reported as "compared, found nothing".
    """
    from pipeline.stages import s10d3_driving_events

    n = 400
    d = np.linspace(0.0, 1200.0, n)
    lap_df = pd.DataFrame({
        "Distance (m)": d, "distance_norm": d / 1200.0,
        "Speed (m/s)": np.full(n, 15.0),
        "Lateral acceleration (G) *calc": np.full(n, 0.9),
        # Strong, sustained deceleration across the WHOLE lap (well past the
        # -0.5 m/s^2 floor and the 3-sample run-length floor once masked to
        # the corner) so re_braking has a genuine event to find.
        "Longitudinal acceleration (G) *calc": np.full(n, -1.0),
    })
    corners = [{"corner_id": 1, "s_start": 300.0, "s_end": 400.0}]
    # Deliberately NO apex_speed_mps / corner_time_s / throttle_onset_m on
    # the only lap at this corner -- reference_by_corner[1] will be {}.
    # `grip_anchor_tier` alongside the pct: since the final review's
    # IMPORTANT 1a, `envelope_under_use` REQUIRES the tier -- a percentage
    # whose baseline nobody can name is not quotable, so a metric dict
    # carrying a bare number now reads "insufficient" rather than being
    # judged against an unknown baseline. Tier 1 here so the detector takes
    # its measured path; the tier-2 tautology is covered in
    # test_driving_events.py.
    metrics = [{"lap_number": 1, "corner_id": 1, "grip_anchor_pct": 40.0,
                "grip_anchor_tier": "session_envelope_ellipse_fitted"}]

    out = s10d3_driving_events.run_driving_events(metrics, corners, {1: lap_df})
    cap = out["capability"]

    # (1) reference-free detectors: not starved.
    assert cap["re_braking"] == "detected", cap
    assert cap["envelope_under_use"] == "detected", cap
    re_brake_events = [e for e in out["events"] if e.event_type == "re_braking"]
    envelope_events = [e for e in out["events"] if e.event_type == "envelope_under_use"]
    assert len(re_brake_events) == 1
    assert re_brake_events[0].magnitude == pytest.approx(9.80665, rel=1e-3)
    assert len(envelope_events) == 1
    assert envelope_events[0].magnitude == pytest.approx(40.0)

    # (2) reference-dependent detectors: honestly "insufficient", not a
    # silently-collapsed "not_triggered".
    assert cap["over_slowing"] == "insufficient", cap
    assert cap["late_throttle"] == "insufficient", cap
    assert not any(e.event_type in ("over_slowing", "late_throttle") for e in out["events"])


def test_stage_never_raises_on_malformed_input():
    from pipeline.stages import s10d3_driving_events

    for args in (
        ([], [], {}),
        ([None], [None], {1: None}),
        ([{"lap_number": None, "corner_id": None}], ["junk"], {1: pd.DataFrame()}),
    ):
        out = s10d3_driving_events.run_driving_events(*args)
        assert isinstance(out, dict)
        assert "events" in out and "capability" in out


@pytest.fixture
def _isolated_track_registry(tmp_path, monkeypatch):
    """Keep the pipeline's track-registration write off the tracked
    models/tracks.json -- see the parent branch's test-hygiene incident.

    Returns a `Path`, not a `str`. `_default_db_path` is annotated `-> Path`
    and `load_track_database` calls `path.exists()` on whatever it returns,
    so a `str` here made stage 05_detect_track raise
    `AttributeError: 'str' object has no attribute 'exists'`. That is
    swallowed by `pipeline/helpers.py:93`, so the isolation "worked" only by
    killing track detection outright -- every test using this fixture ran
    with `steps_failed == ['05_detect_track']` and `track_id='unknown_track'`.
    Verified during fix round 1 that correcting it leaves this module's
    driving-events output bit-identical (corner detection is purely
    geometric off lap 1 and never consults the registry). Matches the
    already-correct version at test_distance_frame.py:614.
    """
    import track_detection

    fake_path = tmp_path / "tracks_isolated.json"
    monkeypatch.setattr(track_detection, "_default_db_path", lambda: fake_path)
    return fake_path


def _write_synthetic_csv(tmp_path, n_laps=3):
    """Minimal RaceChrono-style CSV, same column shape as
    test_grip_anchor_pipeline.py's ``_make_pipeline_csv`` (already proven to
    clear column discovery and reach the friction/grip stages of
    ``pipeline.run_full_analysis``) -- copied rather than imported, since
    nothing in this test suite imports across test modules."""
    rng = np.random.default_rng(7)
    n_per_lap = 150
    lap_length = 500.0
    frames = []
    for lap in range(1, n_laps + 1):
        t_start = (lap - 1) * 30.0
        t = np.linspace(t_start, t_start + 25.0, n_per_lap)
        dist = np.linspace(0, lap_length, n_per_lap)
        speed = np.full(n_per_lap, 20.0) + rng.normal(0, 0.5, n_per_lap)
        lat = np.linspace(45.0, 45.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        lon = np.linspace(9.0, 9.002, n_per_lap) + rng.normal(0, 1e-5, n_per_lap)
        frames.append(pd.DataFrame({
            "Lap #": np.full(n_per_lap, lap),
            "Time (s)": t,
            "Distance (m)": dist + (lap - 1) * lap_length,
            "Speed (m/s)": speed,
            "Latitude (deg)": lat,
            "Longitude (deg)": lon,
            "Bearing (deg)": np.full(n_per_lap, 90.0) + rng.normal(0, 1, n_per_lap),
            "Longitudinal acceleration (G) *calc": rng.normal(0, 0.02, n_per_lap),
            "Lateral acceleration (G) *calc": rng.normal(0, 0.4, n_per_lap),
        }))
    csv_path = tmp_path / "driving_events_wiring_test.csv"
    pd.concat(frames, ignore_index=True).to_csv(csv_path, index=False)
    return csv_path


def test_orchestrator_runs_the_driving_events_stage(_isolated_track_registry, tmp_path):
    """Behavioural: spy on the stage while driving the real orchestrator.

    Mirrors test_grip_anchor_pipeline.py's orchestrator spy exactly -- patch
    run_per_lap_corner_metrics to return a fixed non-empty list (synthetic-CSV
    corner detection is unreliable), then assert the stage under test was
    actually called. A source-grep would pass even if it were wired into dead
    code.
    """
    from unittest.mock import patch
    from pipeline.stages import s10b_corners, s10d3_driving_events
    import pipeline

    fixed = [
        {"lap_number": 1, "corner_id": 1, "apex_speed_mps": 10.0,
         "corner_time_s": 10.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 70.0},
        {"lap_number": 2, "corner_id": 1, "apex_speed_mps": 12.5,
         "corner_time_s": 8.0, "corner_time_best_s": 8.0,
         "grip_anchor_pct": 99.0},
    ]
    csv_path = _write_synthetic_csv(tmp_path)

    with patch.object(s10b_corners, "run_per_lap_corner_metrics",
                      return_value=fixed), \
         patch.object(s10d3_driving_events, "run_driving_events",
                      wraps=s10d3_driving_events.run_driving_events) as spy:
        pipeline.run_full_analysis(str(csv_path), {})

    assert spy.call_count == 1, "the driving-events stage was never called"
    assert spy.call_args.args[0] == fixed


# ══════════════════════════════════════════════════════════════════
# Task 10 — persistence and the two read surfaces
# ══════════════════════════════════════════════════════════════════


def test_ranked_events_are_ordered_by_time_cost(test_db):
    from web.repos import events_repo
    import driving_events as de

    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=L, corner_id=C,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=cost,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"apex_speed_mps": 10.0},
        )
        for (L, C, cost) in [(1, 1, 0.10), (7, 4, 0.885), (9, 1, 0.412)]
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    got = events_repo.get_ranked_events(test_db, "s1", limit=2)
    assert [round(g["time_cost_s"], 3) for g in got] == [0.885, 0.412]
    assert got[0]["lap_number"] == 7 and got[0]["corner_id"] == 4


def test_corner_consistency_reports_best_median_and_spread(test_db):
    from web.repos import events_repo
    import driving_events as de

    # corner 4 is inconsistent, corner 2 is tight
    rows = [(4, 0.0), (4, 0.45), (4, 0.89), (2, 0.0), (2, 0.05), (2, 0.09)]
    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=i + 1, corner_id=c,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=cost,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        )
        for i, (c, cost) in enumerate(rows)
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    by_corner = {r["corner_id"]: r for r in
                 events_repo.get_corner_consistency(test_db, "s1")}
    assert by_corner[4]["spread_s"] > by_corner[2]["spread_s"]
    assert by_corner[4]["worst_s"] == pytest.approx(0.89)
    # Fix round 1 (IMPORTANT #2): median_s and best_s were previously
    # unpinned -- the reviewer swapped median(costs) for a hardcoded
    # 123.456 and best for -999.0 and this test still passed. sorted(corner
    # 4) = [0.0, 0.45, 0.89] -> median is the middle value, 0.45; sorted
    # (corner 2) = [0.0, 0.05, 0.09] -> median 0.05. best_s is min(costs)
    # for each corner: 0.0 in both cases here (not distinguishing, hence
    # the separate dedupe test below pins a best_s that isn't 0.0 too).
    assert by_corner[4]["median_s"] == pytest.approx(0.45)
    assert by_corner[2]["median_s"] == pytest.approx(0.05)
    assert by_corner[4]["best_s"] == pytest.approx(0.0)
    assert by_corner[2]["best_s"] == pytest.approx(0.0)


def test_corner_consistency_dedupes_a_lap_that_fired_multiple_detectors(test_db):
    """Fix round 1, IMPORTANT #1: over_slowing and late_throttle both set
    time_cost_s = corner_time - reference_corner_time for the SAME
    (lap, corner) -- see driving_events.py's _OverSlowing/_LateThrottle
    .detect. Two event rows for the same lap must count as ONE lap's gap,
    not two, or the median gets pulled toward whichever corner fired the
    most detectors.

    Concrete failure the reviewer caught: corner 4 with per-lap gaps
    [0.10, 0.50, 0.90], BOTH over_slowing and late_throttle firing on the
    lap that measured 0.10. Naive median-of-4-rows ([0.10, 0.10, 0.50,
    0.90]) gives (0.10+0.50)/2 = 0.30. The honest median-of-3-distinct-laps
    is 0.50 -- the middle value, since lap 1's duplicate must collapse to
    one observation before the median is taken.
    """
    from web.repos import events_repo
    import driving_events as de

    evs = [
        # Lap 1, corner 4: BOTH detectors fire with the same time_cost_s.
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.10,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="late_throttle", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m", time_cost_s=0.10,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=2, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.50,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=3, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    by_corner = {r["corner_id"]: r for r in
                 events_repo.get_corner_consistency(test_db, "s1")}
    assert by_corner[4]["median_s"] == pytest.approx(0.50), (
        "median must be computed over distinct (lap, corner) pairs, not "
        "event rows -- a duplicated lap must not shift it toward 0.30"
    )
    assert by_corner[4]["best_s"] == pytest.approx(0.10)
    assert by_corner[4]["worst_s"] == pytest.approx(0.90)
    assert by_corner[4]["spread_s"] == pytest.approx(0.80)


def test_ranked_events_dedupes_a_lap_that_fired_multiple_detectors(test_db):
    """Fix round 1, IMPORTANT #1, ranked-list half. Decision recorded in
    the fix report: the ranked list also dedupes to ONE entry per distinct
    (lap_number, corner_id) -- a driver wants N distinct places to work
    on, not the same corner twice under two labels."""
    from web.repos import events_repo
    import driving_events as de

    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="late_throttle", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=2, corner_id=1,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.50,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    got = events_repo.get_ranked_events(test_db, "s1", limit=10)
    assert len(got) == 2, "the two rows for (lap=1, corner=4) must collapse to one"
    keys = [(g["lap_number"], g["corner_id"]) for g in got]
    assert keys == [(1, 4), (2, 1)]


def _co_firing_pair():
    """over_slowing + late_throttle on the SAME (lap, corner), with the
    IDENTICAL time_cost_s -- exactly how the two detectors emit, since both
    compute `corner_time - reference_corner_time` for that corner-lap."""
    import driving_events as de

    return [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.4,
            magnitude_unit="m/s", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="late_throttle", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=12.4,
            magnitude_unit="m", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
    ]


def test_the_dedupe_survivor_is_chosen_by_priority_not_by_row_order():
    """Fix round 2. `over_slowing` and `late_throttle` co-fire on 68% of
    measured late_throttle events on the real fixture and carry the identical
    `time_cost_s`, so "keep the first row seen" meant SQL row order decided
    WHICH OF TWO DIFFERENT CORRECTIONS the driver was shown on most of them.

    Driven at the function directly, in BOTH input orders, because the point
    is precisely that the input order must not matter."""
    from web.repos import events_repo

    forward = [
        {"lap_number": 1, "corner_id": 4, "event_type": "over_slowing",
         "magnitude": 1.4, "magnitude_unit": "m/s", "evidence": {"x": 1}},
        {"lap_number": 1, "corner_id": 4, "event_type": "late_throttle",
         "magnitude": 12.4, "magnitude_unit": "m", "evidence": {"x": 1}},
    ]
    reverse = list(reversed(forward))

    for label, rows in (("over_slowing first", forward),
                        ("late_throttle first", reverse)):
        out = events_repo._dedupe_by_lap_corner([dict(r) for r in rows])
        assert len(out) == 1, label
        assert out[0]["event_type"] == "over_slowing", (
            f"{label}: the survivor must be the direct measurement, not "
            f"whichever row the database happened to hand over first")
        # The loser is recorded, not discarded.
        also = out[0]["evidence"]["also_fired"]
        assert [a["event_type"] for a in also] == ["late_throttle"], label
        assert also[0]["magnitude"] == 12.4, label
        assert also[0]["magnitude_unit"] == "m", label


def test_the_gate_uses_a_true_median_not_the_upper_middle_value():
    """Fix round 2: the onset-correlation assertion was evaluating
    `sorted(x)[len(x) // 2]`, the UPPER-MIDDLE value, while every comment and
    the report documented the true median. With 8 corners that is always the
    even case, so the two always differ. Both cleared the floor, so no
    assertion failed -- which is exactly why this needs its own test: the
    documented headroom was overstated by ~25% with nothing to catch it.

    Pinned on the real per-corner values from the shipped basis.
    """
    real_corner_corrs = [-0.097, -0.292, -0.703, -0.835,
                         -0.484, -0.324, 0.249, -0.874]

    assert _median(real_corner_corrs) == pytest.approx(-0.404, abs=5e-4)
    # the statistic that used to be evaluated, for contrast
    assert sorted(real_corner_corrs)[len(real_corner_corrs) // 2] == \
        pytest.approx(-0.324, abs=5e-4)

    assert _median([3.0, 1.0, 2.0]) == pytest.approx(2.0)      # odd
    assert _median([1.0, 2.0, 3.0, 4.0]) == pytest.approx(2.5)  # even
    assert _median([5.0]) == pytest.approx(5.0)


def test_the_dedupe_priority_covers_every_registered_detector():
    """A fifth detector added without a priority line falls back to
    first-row-wins, silently reintroducing the row-order nondeterminism this
    function was written to remove. Verified by execution: two unranked types
    on one key give two different outputs depending on input order."""
    import driving_events as de
    from web.repos import events_repo

    assert set(events_repo._DEDUPE_PRIORITY) == de.EVENT_TYPES
    events_repo._assert_dedupe_priority_is_total()

    # And the guard actually fires when coverage is lost.
    original = dict(events_repo._DEDUPE_PRIORITY)
    try:
        events_repo._DEDUPE_PRIORITY.pop("re_braking")
        with pytest.raises(AssertionError, match="does not cover EVENT_TYPES"):
            events_repo._dedupe_by_lap_corner([])
    finally:
        events_repo._DEDUPE_PRIORITY.clear()
        events_repo._DEDUPE_PRIORITY.update(original)


def test_the_dedupe_records_the_loser_rather_than_dropping_it(test_db):
    """End to end through the ranked surface: one entry for the corner-lap,
    carrying BOTH facets, so Phase 3 can render a single item that says what
    happened at the apex AND on the exit."""
    from web.repos import events_repo

    events_repo.insert_driving_events(test_db, "s1", _co_firing_pair())
    test_db.commit()

    got = events_repo.get_ranked_events(test_db, "s1", limit=10)

    assert len(got) == 1
    assert got[0]["event_type"] == "over_slowing"
    assert got[0]["magnitude"] == pytest.approx(1.4)
    also = got[0]["evidence"]["also_fired"]
    assert [a["event_type"] for a in also] == ["late_throttle"]
    assert also[0]["magnitude"] == pytest.approx(12.4)


def test_the_dedupe_leaves_cost_only_rows_alone():
    """The consistency query selects lap/corner/cost only. Those rows have no
    `event_type`, so there is no facet to record -- inventing an `also_fired`
    entry of `{"event_type": None}` there would dress a bare cost up as
    detector detail it never carried."""
    from web.repos import events_repo

    rows = [{"lap_number": 1, "corner_id": 4, "time_cost_s": 0.90},
            {"lap_number": 1, "corner_id": 4, "time_cost_s": 0.90}]
    out = events_repo._dedupe_by_lap_corner([dict(r) for r in rows])

    assert len(out) == 1
    assert "evidence" not in out[0] or "also_fired" not in (out[0].get("evidence") or {})


def test_ranked_events_limit_applies_after_dedup_not_before(test_db):
    """Fix round 1: a duplicate detector-pair must not consume two of the
    limit's slots. Corner 4/lap 1 fires two detectors (the highest cost,
    0.90) plus two other distinct (lap, corner) pairs -- asking for the
    top 2 distinct problems must return those 2 distinct pairs, not corner
    4/lap 1 twice with the third pair silently dropped."""
    from web.repos import events_repo
    import driving_events as de

    evs = [
        de.DrivingEvent(
            event_type="over_slowing", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="late_throttle", lap_number=1, corner_id=4,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m", time_cost_s=0.90,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=2, corner_id=1,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.50,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
        de.DrivingEvent(
            event_type="over_slowing", lap_number=3, corner_id=2,
            s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0,
            magnitude_unit="m/s", time_cost_s=0.30,
            validity=de.VALIDITY_MEASURED, reason=None,
            anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
            n_samples_in_window=40, evidence={"x": 1},
        ),
    ]
    events_repo.insert_driving_events(test_db, "s1", evs)
    test_db.commit()

    got = events_repo.get_ranked_events(test_db, "s1", limit=2)
    keys = [(g["lap_number"], g["corner_id"]) for g in got]
    assert keys == [(1, 4), (2, 1)], (
        "limit=2 must return 2 DISTINCT (lap, corner) pairs, not the same "
        "pair counted twice with the third pair dropped"
    )


def test_insert_is_idempotent_so_reprocess_does_not_double(test_db):
    from web.repos import events_repo
    import driving_events as de

    ev = de.DrivingEvent(
        event_type="over_slowing", lap_number=1, corner_id=1,
        s_norm_start=0.2, s_norm_end=0.3, magnitude=1.0, magnitude_unit="m/s",
        time_cost_s=0.2, validity=de.VALIDITY_MEASURED, reason=None,
        anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
        n_samples_in_window=40, evidence={"x": 1},
    )
    events_repo.insert_driving_events(test_db, "s1", [ev])
    events_repo.insert_driving_events(test_db, "s1", [ev])
    test_db.commit()

    n = test_db.execute(
        "SELECT count(*) FROM driving_events WHERE session_id='s1'").fetchone()[0]
    assert n == 1


def test_insert_coerces_numpy_evidence_to_json_safe_types(test_db):
    """Resolution #4: evidence may contain numpy scalars. np.int64/np.bool_/
    np.float32 are NOT subclasses of Python's int/bool/float, so json.dumps
    raises TypeError on them directly (confirmed against this repo's own
    numpy build) -- and Phase 1 lost an entire corner_metrics write to the
    equivalent bind-time version of this bug because the exception was
    swallowed. If insert_driving_events doesn't coerce, this test raises
    TypeError instead of asserting anything -- that failure mode is itself
    the point being guarded against."""
    from web.repos import events_repo
    import driving_events as de
    import json

    ev = de.DrivingEvent(
        event_type="envelope_under_use", lap_number=1, corner_id=1,
        s_norm_start=0.2, s_norm_end=0.3, magnitude=float(np.float64(42.0)),
        magnitude_unit="pct", time_cost_s=None,
        validity=de.VALIDITY_MEASURED, reason=None,
        anchor_tier=de.ANCHOR_DRIVER_BEST_SESSION,
        n_samples_in_window=40,
        evidence={
            "grip_anchor_pct": np.float64(42.0),
            "sample_count": np.int64(40),
            "clean": np.bool_(True),
            "floor_pct": np.float32(100.0),
        },
    )
    events_repo.insert_driving_events(test_db, "s1", [ev])
    test_db.commit()

    row = test_db.execute(
        "SELECT evidence_json FROM driving_events WHERE session_id='s1'"
    ).fetchone()
    parsed = json.loads(row["evidence_json"])
    assert parsed == {
        "grip_anchor_pct": 42.0, "sample_count": 40,
        "clean": True, "floor_pct": 100.0,
    }


# ── Endpoints: tenancy scoping (resolution #3) ─────────────────────
#
# Mirrors tests/test_idor_theoretical_user_corners.py's mock-based pattern
# exactly (that file's own header explains why: two confirmed cross-tenant
# blockers were routes that queried a child table by client-supplied
# session_id without first resolving ownership through
# models.get_session_by_id() on the RLS-scoped request connection). A
# session_id outside the caller's workspace must 404 and must NEVER reach
# events_repo.


@pytest.fixture
def data_v2_client():
    """Minimal Flask app with only the data_v2 blueprint -- no real DB."""
    from flask import Flask
    from web.routes.data_v2 import bp

    app = Flask(__name__)
    app.config["TESTING"] = True
    app.config["USE_PG"] = False
    app.register_blueprint(bp)
    return app.test_client()


class TestDrivingEventsIdorGuard:

    @pytest.mark.parametrize("path", [
        "/api/v1/sessions/foreign-session/driving-events",
        "/api/v1/sessions/foreign-session/corner-consistency",
    ])
    def test_404_when_session_not_visible_to_caller(self, data_v2_client, path):
        """A non-owner (session invisible on the RLS-scoped connection, i.e.
        get_session_by_id returns None) must get 404, and events_repo must
        never be touched -- proves the guard fires before any query, not
        just that the final response happens to omit foreign data.

        events_repo's mocked return values are deliberately JSON-serializable
        (fix round 1, MINOR): a plain MagicMock return value makes a
        guard-removed regression fail on a 500 (Flask's jsonify choking on
        the MagicMock) before the load-bearing assert_not_called() ever
        runs, and before resp.status_code == 404 can distinguish "guard
        denied" from "guard skipped, then something else broke". With a
        real list here, removing the guard instead surfaces an explicit
        200-with-foreign-rows -- the actual thing this test exists to catch.
        """
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models, \
                patch("web.routes.data_v2.events_repo") as mock_events_repo:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = None
            mock_events_repo.get_ranked_events.return_value = [
                {"lap_number": 1, "corner_id": 1, "time_cost_s": 0.5},
            ]
            mock_events_repo.get_corner_consistency.return_value = [
                {"corner_id": 1, "best_s": 0.0, "worst_s": 0.5,
                 "median_s": 0.25, "spread_s": 0.5,
                 "anchor_tiers": ["driver_best_session"]},
            ]
            mock_events_repo.get_driving_events_capability.return_value = {
                "over_slowing": "detected",
            }

            resp = data_v2_client.get(path)

            assert resp.status_code == 404, resp.get_data(as_text=True)
            body = resp.get_json()
            assert body["ok"] is False
            assert body["error"]["code"] == "NOT_FOUND"
            mock_events_repo.get_ranked_events.assert_not_called()
            mock_events_repo.get_corner_consistency.assert_not_called()

    def test_owner_gets_ranked_events(self, data_v2_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models, \
                patch("web.routes.data_v2.events_repo") as mock_events_repo:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = {"session_id": "s1", "workspace_id": 1}
            mock_events_repo.get_ranked_events.return_value = [
                {"lap_number": 7, "corner_id": 4, "time_cost_s": 0.885},
            ]
            mock_events_repo.get_driving_events_capability.return_value = {
                "over_slowing": "detected", "late_throttle": "detected",
                "re_braking": "not_triggered",
                "envelope_under_use": "insufficient",
            }

            resp = data_v2_client.get("/api/v1/sessions/s1/driving-events?limit=5")

            assert resp.status_code == 200, resp.get_data(as_text=True)
            body = resp.get_json()
            assert body["ok"] is True
            assert body["data"]["events"][0]["corner_id"] == 4
            mock_events_repo.get_ranked_events.assert_called_once_with(
                mock_db.return_value, "s1", limit=5,
            )
            # IMPORTANT 2: the capability record reaches the consumer.
            assert body["data"]["capability"]["envelope_under_use"] == "insufficient"
            assert body["data"]["capability_available"] is True

    def test_owner_gets_corner_consistency(self, data_v2_client):
        with patch("web.routes.data_v2.get_db_connection") as mock_db, \
                patch("web.routes.data_v2.models") as mock_models, \
                patch("web.routes.data_v2.events_repo") as mock_events_repo:
            mock_db.return_value = MagicMock()
            mock_models.get_session_by_id.return_value = {"session_id": "s1", "workspace_id": 1}
            mock_events_repo.get_corner_consistency.return_value = [
                {"corner_id": 4, "best_s": 0.0, "worst_s": 0.89,
                 "median_s": 0.45, "spread_s": 0.89},
            ]

            resp = data_v2_client.get("/api/v1/sessions/s1/corner-consistency")

            assert resp.status_code == 200, resp.get_data(as_text=True)
            body = resp.get_json()
            assert body["ok"] is True
            assert body["data"]["corners"][0]["spread_s"] == pytest.approx(0.89)
            mock_events_repo.get_corner_consistency.assert_called_once_with(
                mock_db.return_value, "s1",
            )


# ══════════════════════════════════════════════════════════════════
# Task 12 fix round 2 — the ingestion path is a precondition, not a detail
# ══════════════════════════════════════════════════════════════════

def test_the_adapter_registry_is_reachable_without_the_launcher_helping():
    """`run_ingest` selects its reader with `from telemetry_tool.adapters
    import parse_file` -- an absolute package import needing the REPO ROOT on
    sys.path. When that failed it was swallowed by a bare `except: pass` and
    the run silently continued down the legacy io_racechrono reader, which
    hands corner detection different column names: measured on the same file,
    8 corners / 72 corner-laps / 141 events one way and 6 / 42 / 93 the other.

    Run in a SUBPROCESS with sys.path deliberately set to the broken shape
    (`telemetry_tool/` only, no repo root), because that shape cannot be
    reproduced inside pytest -- the runner has already put the root on the
    path, and tearing it out mid-session would break every later import.
    """
    import subprocess
    import sys as _sys

    repo_root = Path(__file__).resolve().parents[2]
    script = "\n".join([
        "import sys, pathlib",
        # The broken shape: telemetry_tool/ is importable, the repo root is not.
        "try:",
        "    import telemetry_tool",
        "    raise SystemExit('PRECONDITION-NOT-MET')",
        "except ImportError:",
        "    pass",
        "from pipeline.stages import s01_ingest",
        "root = str(pathlib.Path(s01_ingest.__file__).resolve().parents[3])",
        # Drive `run_ingest` itself, NOT the helper: a bite-check showed that
        # calling `_ensure_package_root_on_path()` directly still passes when
        # the call site has been deleted from `run_ingest`, which is exactly
        # the regression that matters.
        "df, info = s01_ingest.run_ingest(r'%s')" % (
            repo_root / "telemetry_tool" / "data" / "raw" / "OK_R4.csv"),
        "assert df is not None and not df.empty, 'ingest produced nothing'",
        "assert info.get('ingest_path') == s01_ingest.INGEST_PATH_ADAPTER, (",
        "    'run_ingest fell back to %r' % info.get('ingest_path'))",
        "assert 'Satellites' in df.columns, sorted(df.columns)[:12]",
        "n = sys.path.count(root)",
        "s01_ingest._ensure_package_root_on_path()",
        "assert sys.path.count(root) == n, 'not idempotent'",
        "print('OK')",
    ])
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_root / "telemetry_tool")
    proc = subprocess.run(
        [_sys.executable, "-c", script],
        capture_output=True, text=True, env=env,
        # NOT the repo root: `python -c` puts the cwd on sys.path, which would
        # hand the subprocess the very entry this test removes.
        cwd=str(repo_root.parent),
    )
    assert "PRECONDITION-NOT-MET" not in proc.stdout + proc.stderr, (
        "the probe could not reproduce a process without the repo root on "
        "sys.path, so it proves nothing")
    assert proc.returncode == 0 and "OK" in proc.stdout, (
        f"the adapter registry stayed unreachable:\n"
        f"stdout={proc.stdout}\nstderr={proc.stderr[-2000:]}")


def test_the_ingest_path_is_recorded_so_constants_carry_their_precondition():
    from pipeline.stages import s01_ingest

    assert s01_ingest.INGEST_PATH_ADAPTER != s01_ingest.INGEST_PATH_LEGACY
    src = inspect.getsource(s01_ingest.run_ingest)
    assert 'source_info["ingest_path"] = INGEST_PATH_ADAPTER' in src
    assert 'source_info["ingest_path"] = INGEST_PATH_LEGACY' in src


def test_the_window_builder_threads_the_onset_status_onto_the_window():
    """Nothing else asserts this link directly -- it was covered only
    indirectly, via the real-data gate's capability assertion. A window built
    without the status silently makes `late_throttle` read "insufficient" for
    that corner-lap, which looks like missing data rather than a wiring bug.
    """
    import driving_events as de
    from pipeline.stages import s10d3_driving_events as s10d3

    n = 400
    d = np.linspace(0.0, 1200.0, n)
    lap_df = pd.DataFrame({
        "Distance (m)": d, "distance_norm": d / 1200.0,
        "Speed (m/s)": np.full(n, 15.0),
        "Lateral acceleration (G) *calc": np.full(n, 0.9),
        "Longitudinal acceleration (G) *calc": np.zeros(n),
    })
    corner = {"corner_id": 1, "s_start": 300.0, "s_end": 400.0}
    metric = {"lap_number": 1, "corner_id": 1, "corner_time_s": 8.0,
              "throttle_onset_m": None,
              "throttle_onset_status": de.ONSET_NO_SPEED_CROSSING}

    window = s10d3._build_one_window(
        1, 1, corner, metric, lap_df, lap_df, {"corner_time_s": 7.5},
    )
    assert window is not None
    assert window.throttle_onset_status == de.ONSET_NO_SPEED_CROSSING


# ══════════════════════════════════════════════════════════════════
# Task 12 — throttle onset: one threshold per corner, not one per lap
# ══════════════════════════════════════════════════════════════════
#
# The defect: `throttle_onset_m` used to be the first post-apex sample above
# THIS LAP'S OWN apex speed + 0.5 m/s. Because dv/ds = a/v on a constant-
# acceleration exit, a lap carrying MORE apex speed needs MORE distance to
# gain that same 0.5 m/s -- so the faster lap's onset was reported LATER and
# the metric was anti-correlated with corner performance. The threshold is
# now per-corner and session-fixed.

_ONSET_ACCEL_MPS2 = 3.0
_ONSET_APEX_M = 150.0
_ONSET_CRUISE_MPS = 30.0
_ONSET_LAP_M = 600.0
_ONSET_STEP_M = 0.5


def _exit_lap(apex_speed_mps):
    """A lap frame whose speed dips to `apex_speed_mps` at `_ONSET_APEX_M`
    and accelerates out of it at a constant `_ONSET_ACCEL_MPS2`.

    ``v(s) = sqrt(v_apex^2 + 2*a*|s - s_apex|)`` is the real shape of a
    constant-acceleration exit, and using it rather than a straight line is
    load-bearing: it is what makes the removed per-lap rule measurably
    invert, so this fixture actually exhibits the defect being fixed.
    """
    d = np.arange(0.0, _ONSET_LAP_M, _ONSET_STEP_M)
    v = np.minimum(
        _ONSET_CRUISE_MPS,
        np.sqrt(apex_speed_mps ** 2
                + 2 * _ONSET_ACCEL_MPS2 * np.abs(d - _ONSET_APEX_M)),
    )
    return pd.DataFrame({
        "Distance (m)": d,
        "distance_norm": d / _ONSET_LAP_M,
        "Speed (m/s)": v,
    })


def _onsets_for(apex_speeds, corners=None):
    """Run the real two-pass derivation over one synthetic lap per entry in
    `apex_speeds`, all through the same corner. Returns {lap_number: metric}.
    """
    from pipeline.stages import s10b_corners as s10b

    corners = corners or [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    laps, metrics, pending = {}, {}, []
    for lap_number, apex in enumerate(apex_speeds, start=1):
        lap_df = _exit_lap(apex)
        laps[lap_number] = lap_df
        m = dict(lap_number=lap_number, corner_id=1,
                 s_start=corners[0]["s_start"], s_end=corners[0]["s_end"])
        apex_idx = s10b._enrich_corner_telemetry(m, lap_df)
        metrics[lap_number] = m
        pending.append((lap_number, m, apex_idx))
    s10b._assign_throttle_onsets(pending, laps, corners)
    return metrics


def _onset_under_the_removed_rule(lap_df, apex_idx):
    """The rule this task deleted, reproduced verbatim so the fixture can be
    shown to exhibit the defect. This is a fixture property, not a second
    implementation of anything that ships -- the code it mirrors no longer
    exists, so it cannot drift out of step with production."""
    v = lap_df["Speed (m/s)"].values
    d = lap_df["Distance (m)"].values
    for k in range(apex_idx + 1, min(apex_idx + 50, len(v) - 2)):
        if v[k] > v[apex_idx] + 0.5 and v[k + 1] > v[k]:
            return float(d[k])
    return None


def test_the_removed_onset_rule_really_did_report_the_faster_lap_as_later():
    """Guards the FIXTURE, not the fix. Every assertion in the next test is
    worthless if these three laps do not actually exhibit the inversion, so
    prove it here: under the removed per-lap rule, onset RISES with apex
    speed -- the faster the lap, the later it is reported."""
    from pipeline.stages import s10b_corners as s10b

    old = []
    for apex in (14.0, 17.0, 20.0):
        lap_df = _exit_lap(apex)
        m = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
        apex_idx = s10b._enrich_corner_telemetry(m, lap_df)
        old.append(_onset_under_the_removed_rule(lap_df, apex_idx))

    assert None not in old
    assert old[0] < old[1] < old[2], (
        f"the fixture does not exhibit the defect: onsets {old} do not rise "
        f"with apex speed under the removed rule")


def test_the_onset_threshold_is_session_fixed_so_the_faster_lap_is_earlier():
    """Three laps, apex speeds 14 / 17 / 20 m/s through one corner.

    The session-fixed threshold is max(14, 17, 20) + 0.5 = 20.5 m/s, so every
    lap is measured against the SAME absolute speed and each onset is
    analytically predictable from v(s) = sqrt(v_apex^2 + 2*a*(s - s_apex)).
    Pinning all three to that one number is what proves a single shared
    threshold governed them -- a per-lap threshold cannot produce this set.
    """
    import driving_events as de

    metrics = _onsets_for([14.0, 17.0, 20.0])
    onsets = [metrics[i]["throttle_onset_m"] for i in (1, 2, 3)]
    assert all(m["throttle_onset_status"] == de.ONSET_MEASURED
               for m in metrics.values())

    # THE PROPERTY: faster apex -> earlier onset. The exact inversion of what
    # the removed rule produced (previous test).
    assert onsets[2] < onsets[1] < onsets[0], (
        f"onset must fall as apex speed rises, got {onsets}")

    # And each one lands on the 20.5 m/s crossing, within one sample.
    threshold = 20.5
    for apex, onset in zip((14.0, 17.0, 20.0), onsets):
        gain = max(threshold ** 2 - apex ** 2, 0.0)
        expected = _ONSET_APEX_M + gain / (2 * _ONSET_ACCEL_MPS2)
        assert abs(onset - expected) <= _ONSET_STEP_M, (
            f"apex {apex}: onset {onset} is not the {threshold} m/s crossing "
            f"(expected ~{expected})")

    # NO DEGENERATE ONSET (fix round 2). The session BEST basis was chosen
    # over the session median precisely because its threshold sits at or
    # above every lap's own apex speed, so no lap can already be above it AT
    # the apex and no onset can collapse onto the apex position. A basis
    # inside the apex distribution -- the median -- puts the fastest lap's
    # onset one sample past the apex, where the number reported is "where the
    # apex is", not "where the driver got back on the power".
    for lap_number, m in metrics.items():
        assert m["throttle_onset_m"] > _ONSET_APEX_M + 2 * _ONSET_STEP_M, (
            f"lap {lap_number}'s onset {m['throttle_onset_m']} is on top of "
            f"the apex at {_ONSET_APEX_M} -- the metric has degenerated into "
            f"reporting the apex position")


def _slow_exit_lap():
    """Speed sits at 10 m/s from the corner all the way to 260 m, then rises.
    The only crossing of a ~10.5 m/s threshold is at ~260 m -- past a
    neighbouring corner at 250 m, and inside the search window without one.
    """
    d = np.arange(0.0, _ONSET_LAP_M, _ONSET_STEP_M)
    v = np.full_like(d, _ONSET_CRUISE_MPS)
    v[(d >= 100.0) & (d < 260.0)] = 10.0
    tail = d >= 260.0
    v[tail] = np.minimum(_ONSET_CRUISE_MPS, 10.0 + 0.2 * (d[tail] - 260.0))
    return pd.DataFrame({
        "Distance (m)": d,
        "distance_norm": d / _ONSET_LAP_M,
        "Speed (m/s)": v,
    })


def _run_onset_pass(lap_dfs, corners):
    from pipeline.stages import s10b_corners as s10b

    laps, metrics, pending = {}, {}, []
    for lap_number, lap_df in enumerate(lap_dfs, start=1):
        laps[lap_number] = lap_df
        m = dict(lap_number=lap_number, corner_id=1,
                 s_start=corners[0]["s_start"], s_end=corners[0]["s_end"])
        apex_idx = s10b._enrich_corner_telemetry(m, lap_df)
        metrics[lap_number] = m
        pending.append((lap_number, m, apex_idx))
    s10b._assign_throttle_onsets(pending, laps, corners)
    return metrics


def test_the_onset_search_stops_at_the_next_corner():
    """The bound is geometric, not a sample count.

    Identical telemetry, identical threshold; the ONLY difference is whether
    a neighbouring corner starts at 250 m. With one, the crossing at ~260 m
    is inside the NEXT corner and is not this corner's exit at all, so the
    scan must refuse rather than report it.
    """
    import driving_events as de

    lone = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    with_neighbour = lone + [{"corner_id": 2, "s_start": 250.0, "s_end": 300.0}]
    laps = [_slow_exit_lap(), _slow_exit_lap()]

    free = _run_onset_pass(laps, lone)[1]
    bounded = _run_onset_pass(laps, with_neighbour)[1]

    assert free["throttle_onset_status"] == de.ONSET_MEASURED
    # threshold = median apex + 0.5 = 10.5 m/s, reached 2.5 m into the
    # 0.2 m/s-per-metre ramp that starts at 260 m.
    assert free["throttle_onset_m"] == pytest.approx(262.5, abs=_ONSET_STEP_M)

    assert bounded["throttle_onset_m"] is None
    assert bounded["throttle_onset_status"] == de.ONSET_NO_SPEED_CROSSING


def test_a_corner_lap_whose_scan_found_nothing_is_reported_not_dropped():
    """The metric row survives with a named reason. Dropping it would remove
    the lap from the pool the per-corner reference is a minimum over --
    censoring the reference toward the laps whose scan happened to succeed.
    """
    import driving_events as de

    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0},
               {"corner_id": 2, "s_start": 250.0, "s_end": 300.0}]
    metrics = _run_onset_pass([_slow_exit_lap()], corners)

    assert set(metrics) == {1}, "the corner-lap disappeared"
    assert metrics[1]["throttle_onset_m"] is None
    assert metrics[1]["throttle_onset_status"] in de.ONSET_REFUSAL_REASONS


def test_a_corner_too_short_to_hold_an_apex_names_its_own_reason():
    """`onset_no_apex` is reserved for exactly this: the scan had no start
    point. It must not be reported as `onset_no_speed_crossing`, which would
    send someone hunting a driving problem in a geometry problem."""
    import driving_events as de

    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 100.6}]
    metrics = _run_onset_pass([_exit_lap(14.0)], corners)

    assert metrics[1]["throttle_onset_m"] is None
    assert metrics[1]["throttle_onset_status"] == de.ONSET_NO_APEX


def test_the_onset_search_limit_is_the_tighter_of_the_two_bounds():
    from pipeline.stages import s10b_corners as s10b

    corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}   # 100 m long

    # No neighbour: s_end + one corner length.
    assert s10b._onset_search_limit_m(corner, [corner]) == pytest.approx(300.0)

    # A near neighbour wins over s_end + length.
    near = [corner, {"corner_id": 2, "s_start": 250.0, "s_end": 300.0}]
    assert s10b._onset_search_limit_m(corner, near) == pytest.approx(250.0)

    # A far neighbour does not: s_end + length still wins.
    far = [corner, {"corner_id": 2, "s_start": 500.0, "s_end": 550.0}]
    assert s10b._onset_search_limit_m(corner, far) == pytest.approx(300.0)

    # A corner BEHIND this one is not a bound at all.
    behind = [corner, {"corner_id": 0, "s_start": 10.0, "s_end": 50.0}]
    assert s10b._onset_search_limit_m(corner, behind) == pytest.approx(300.0)

    # Degenerate geometry has no search window, and says so rather than
    # guessing a span.
    assert s10b._onset_search_limit_m(
        {"corner_id": 1, "s_start": 200.0, "s_end": 200.0}, []) is None
    assert s10b._onset_search_limit_m(
        {"corner_id": 1, "s_start": "x", "s_end": 200.0}, []) is None


# ══════════════════════════════════════════════════════════════════
# Final review, CRITICAL 1 — the onset's coordinate frame
# ══════════════════════════════════════════════════════════════════
#
# `_scan_onset` used to return a raw per-lap ABSOLUTE metre, and
# `late_throttle` differenced two of those ACROSS laps. Every resampled lap
# is rebased to its own span, so a longer lap put the same tarmac at a
# larger metre and was reported as a later onset. On the real fixture that
# artifact was 43-76% of the observed spread at corners 6-8 -- six to nine
# times the 2.0 m emit floor -- and it flipped the emit decision on 4 of 71
# corner-laps, always in the direction of flagging the longer lap.

_FRAME_STEP_NORM = 1.0 / 1200.0
_FRAME_APEX_NORM = 0.25
_FRAME_ACCEL_PER_NORM = 2 * 3.0 * 600.0   # 3 m/s^2 on a 600 m reference lap


def _norm_identical_lap(lap_m, apex_speed_mps=14.0):
    """A lap whose speed is a fixed function of NORMALISED position.

    Two laps built this way are the same driving over the same tarmac; the
    ONLY difference between them is the lap's absolute length. So any
    cross-lap difference a distance-valued metric reports between them is
    coordinate frame, by construction -- there is no behaviour in the
    fixture for it to be anything else. Same idea as the reviewer's control,
    which took a fixed normalised point and watched its absolute metre move.
    """
    n = np.arange(0.0, 1.0, _FRAME_STEP_NORM)
    v = np.minimum(
        _ONSET_CRUISE_MPS,
        np.sqrt(apex_speed_mps ** 2
                + _FRAME_ACCEL_PER_NORM * np.abs(n - _FRAME_APEX_NORM)),
    )
    return pd.DataFrame({
        "Distance (m)": n * lap_m,
        "distance_norm": n,
        "Speed (m/s)": v,
    })


def test_the_onset_is_reported_in_a_lap_length_invariant_frame():
    """Two laps, identical driving, lap lengths 600 m and 620 m.

    The onset must come back at the SAME normalised position and, once
    converted against the ONE session reference length, at the same metre --
    so `late_throttle`'s cross-lap delta is 0, not 3% of a lap.
    """
    import driving_events as de
    from pipeline.stages import s10b_corners as s10b

    short_m, long_m = 600.0, 620.0
    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    laps = {1: _norm_identical_lap(short_m), 2: _norm_identical_lap(long_m)}

    metrics, pending = {}, []
    for lap_number, lap_df in laps.items():
        m = dict(lap_number=lap_number, corner_id=1,
                 s_start=100.0, s_end=200.0)
        pending.append((lap_number, m, s10b._enrich_corner_telemetry(m, lap_df)))
        metrics[lap_number] = m
    s10b._assign_throttle_onsets(pending, laps, corners)

    assert all(m["throttle_onset_status"] == de.ONSET_MEASURED
               for m in metrics.values()), metrics

    n1 = metrics[1]["throttle_onset_norm"]
    n2 = metrics[2]["throttle_onset_norm"]

    # THE FIXTURE EXHIBITS THE DEFECT. In each lap's OWN absolute metres --
    # which is exactly what the scan used to return -- the same normalised
    # onset sits more than a whole emit floor apart.
    raw_gap = abs(n2 * long_m - n1 * short_m)
    assert raw_gap > de.LATE_THROTTLE_ONSET_FLOOR_M, (
        f"the fixture does not exhibit the frame artifact: raw per-lap "
        f"positions differ by only {raw_gap:.2f} m, under the "
        f"{de.LATE_THROTTLE_ONSET_FLOOR_M} m floor")

    # THE FIX. Same normalised position, and the published metre is the same
    # number on both laps because one reference length converts both.
    assert n1 == pytest.approx(n2, abs=1e-9), (
        f"normalised onsets differ ({n1} vs {n2}) on identical driving")
    delta_m = abs(metrics[2]["throttle_onset_m"]
                  - metrics[1]["throttle_onset_m"])
    assert delta_m < de.LATE_THROTTLE_ONSET_FLOOR_M, (
        f"late_throttle would report a {delta_m:.2f} m magnitude between two "
        f"laps that drove identically -- that is lap length, not throttle "
        f"timing (floor {de.LATE_THROTTLE_ONSET_FLOOR_M} m)")
    assert delta_m == pytest.approx(0.0, abs=1e-6)


def test_the_onset_search_bound_is_in_the_frame_the_scan_runs_in():
    """The bound is derived from the DETECTION lap's geometry, so it must be
    mapped through the DETECTION lap's span -- not applied as a bare metre to
    whatever frame the lap being scanned happens to use.

    Applying it raw shortened the search window on every lap longer than the
    detection lap, systematically censoring the latest onsets on exactly the
    laps most likely to have one.
    """
    from pipeline.stages import s10b_corners as s10b

    corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
    corners = [corner]

    # Detection lap 600 m long: the 300 m bound is half a lap.
    assert s10b._onset_search_limit_norm(
        corner, corners, (0.0, 600.0)) == pytest.approx(0.5)
    # A detection lap of a different length moves the bound, as it must --
    # the bound is a piece of that lap's geometry.
    assert s10b._onset_search_limit_norm(
        corner, corners, (0.0, 1200.0)) == pytest.approx(0.25)
    # A non-zero origin is honoured, matching _corner_mask's own map.
    assert s10b._onset_search_limit_norm(
        corner, corners, (100.0, 400.0)) == pytest.approx(0.5)
    # No frame, no map: refuse rather than compare a metre to a 0-1 array.
    assert s10b._onset_search_limit_norm(corner, corners, None) is None
    # Degenerate geometry still refuses.
    assert s10b._onset_search_limit_norm(
        {"corner_id": 1, "s_start": 200.0, "s_end": 200.0},
        corners, (0.0, 600.0)) is None


def test_a_session_with_no_reference_length_refuses_by_name():
    """No detection-lap span means no metre <-> norm map. Every corner-lap
    must say so with its own status rather than publish a normalised number
    under a metre field name."""
    import driving_events as de
    from pipeline.stages import s10b_corners as s10b

    corners = [{"corner_id": 1, "s_start": 100.0, "s_end": 200.0}]
    lap_df = _norm_identical_lap(600.0)
    m = dict(lap_number=1, corner_id=1, s_start=100.0, s_end=200.0)
    apex_idx = s10b._enrich_corner_telemetry(m, lap_df)

    # A frame with zero span: distance present, but no length to convert by.
    flat = lap_df.copy()
    flat["Distance (m)"] = 0.0
    s10b._assign_throttle_onsets([(1, m, apex_idx)], {1: flat}, corners)

    assert m["throttle_onset_m"] is None
    assert m["throttle_onset_norm"] is None
    assert m["throttle_onset_status"] == de.ONSET_NO_REFERENCE_FRAME
    assert de.ONSET_NO_REFERENCE_FRAME in de.ONSET_REFUSAL_REASONS


def test_the_corner_mask_refuses_when_distance_norm_is_missing():
    """The load-bearing frame contract of this whole branch: a frame with no
    `distance_norm` must produce NO window, never a window silently sliced
    in absolute metres.

    Unguarded until the final review, and it is the exact contract the
    coordinate-frame defect in `throttle_onset_m` survived next to.
    """
    from pipeline.stages import s10d2_grip_anchor as s10d2

    corner = {"corner_id": 1, "s_start": 100.0, "s_end": 200.0}
    lap_df = _norm_identical_lap(600.0)
    detection = lap_df

    # With the column: a real mask.
    mask = s10d2._corner_mask(lap_df, corner, detection)
    assert mask is not None and mask.sum() >= 3

    # Without it: refusal, not an absolute-metre fallback.
    stripped = lap_df.drop(columns=["distance_norm"])
    assert s10d2._corner_mask(stripped, corner, detection) is None


# ══════════════════════════════════════════════════════════════════
# Task 11 — real-data acceptance. This is the gate.
# ══════════════════════════════════════════════════════════════════

# ⚠ ANCHORED TO `__file__`, NOT TO THE CWD. This was
# `"telemetry_tool/data/raw/OK_R4.csv"`, a CWD-relative path sitting under a
# `skipif(not os.path.exists(...))`. Run pytest from `telemetry_tool/` -- an
# entirely reasonable thing to do, and what the package's own `pytest.ini`
# testpaths invite -- and the path missed, every real-data test SKIPPED, and
# pytest exited 0. Measured before the fix: "32 skipped, 56 deselected",
# exit 0.
#
# That is a green run that proved nothing, in the one place this branch's
# numbers are established: the same failure class as a test that cannot
# fail, which is the failure this project cares about most. The skip is
# still there (the fixture is genuinely optional for a clone without it),
# but it can no longer fire just because of where pytest was invoked.
_REAL_CSV = str(
    pathlib.Path(__file__).resolve().parents[1] / "data" / "raw" / "OK_R4.csv"
)


def test_the_real_fixture_path_is_anchored_not_cwd_relative():
    """NEW-3. `_REAL_CSV` sits under a `skipif`, so a CWD-relative path does
    not fail -- it makes every real-data test SKIP and pytest exit 0. Measured
    before the fix, running pytest from `telemetry_tool/`: "32 skipped,
    56 deselected", exit 0. A green run that proved nothing, in the one place
    this branch's numbers are established.

    `isabs` rather than `exists`: this must fail from ANY working directory
    the moment the path stops being anchored, including on a clone where the
    fixture is genuinely absent and the skip is legitimate.
    """
    assert os.path.isabs(_REAL_CSV), (
        f"_REAL_CSV is {_REAL_CSV!r} -- a relative path under a skipif "
        f"silently turns the entire real-data gate into 'skipped, exit 0' "
        f"depending on where pytest was invoked from")

# ── The floors this gate enforces ─────────────────────────────────────────
#
# Fix round 1 rewrote this section. The original gate asserted only
# "some events exist" plus a per-event vocabulary check, and a replay of
# that body against 16 deliberately mutated event lists caught exactly ONE
# of them: `run_registry -> ([], {})`. Everything else sailed through --
# every event flipped to a non-measured validity, every `time_cost_s` set to
# None, all 142 events collapsed onto one corner, only one of four
# detectors ever firing, the whole capability record degraded to
# "insufficient", Task 10's dedupe regressing so every event appeared five
# times. None of those is a subtle failure; all of them are things this
# phase exists to prevent, and none was asserted.
#
# The rule each constant below follows: anchor on the value MEASURED on this
# fixture, then sit far enough below it that honest track-to-track variation
# cannot trip the floor, while staying far above the collapse it exists to
# catch. That gap is wide here because the failure modes are systemic --
# they take the whole session to zero or to one, not to "somewhat less".
# Same reasoning, and the same shape, as
# test_grip_anchor_pipeline.py's _MIN_SESSION_ENVELOPE_SHARE.

# MEASURED: 72 corner-laps (8 detected corners x 9 admissible laps).
# 24 = 4 corners x 6 laps: the smallest session shape in which a per-corner
# "the driver's own best" reference means anything at all. Below 6 laps a
# per-corner best is one lucky pass rather than a reference, and below 4
# corners this is not a circuit. Every way this collapses is structural, not
# gradual -- corner detection regressing (8 -> 2 corners gives 18) or the
# admissible-lap set collapsing takes it well under 24 in one step -- so the
# 3x headroom below the measured 72 costs nothing in sensitivity.
_MIN_CORNER_LAPS = 24

# MEASURED: 140 events. 141 before the final review; the coordinate-frame
# fix dropped two late_throttle events below the emit floor (-2) and the
# tier-2 refusal turned 14 measured envelope_under_use events into 15
# not_measurable ones (+1). Catches the "events collapse to 4" mutation.
# With four detectors over >= 24 corner-laps, and the two reference-comparison
# detectors structurally able to fire on up to 8 of every 9 laps per corner
# (only the record-holding lap is silent), a functioning session cannot come
# back with a single-digit event count. 30 keeps ~4.7x headroom under the
# measured value while being ~7x above the collapse case.
_MIN_EVENTS = 30

# MEASURED: 124/140 = 88.6% of events are validity="measured". The 16
# exceptions are all genuine, located refusals: 15 envelope_under_use
# events refusing a self-referential tier-2 grip anchor (final review,
# IMPORTANT 1b) and 1 late_throttle whose onset scan found no crossing.
# The share fell from 99.3% BECAUSE the branch learned to refuse; the
# floor was already set at 0.80 to leave room for exactly this.
# Catches every wholesale validity flip. Deliberately NOT pinned at 1.0:
# the spec explicitly wants a future detector to be able to emit an honest
# `Insufficient` on windows where a channel is missing, and pinning 100%
# here would make that correct behaviour fail this gate. 0.80 still fails
# instantly on the mutation that matters -- a systemic flip drives the
# measured share to ZERO, because validity is decided per detector from
# session-wide inputs, not per event.
_MIN_MEASURED_SHARE = 0.80

# MEASURED: events on all 8 corners and all 9 laps.
# Catches "all events from one corner", "every corner_id = 1", and corner
# detection regressing 8 -> 2. Half the detected corners is the right order:
# a real session shows problems in several distinct places, and every
# collapse mode drives this to 1 or 2.
_MIN_DISTINCT_CORNERS = 4
_MIN_DISTINCT_LAPS = 4

# MEASURED: 44 of 140 events carry a time_cost_s -- `over_slowing` ONLY,
# since the 2026-08-06 ruling took `late_throttle`'s cost away (it was
# `over_slowing`'s own number, measured once and claimed twice). re_braking
# and envelope_under_use never had one.
#
# Catches "every time_cost_s = None". time_cost_s is the ranking key -- it
# is the entire reason the ranked read surface exists -- so a session that
# produces events but no costs has silently lost the product feature while
# staying green. HEADROOM NARROWED from ~5x to 2.2x when the ruling halved
# the costed set; 20 still fails instantly on the collapse it exists to
# catch (which drives this to ZERO, not to "somewhat fewer"), and lowering
# the floor to restore the old ratio would weaken it for no measured
# reason.
#
# The onset-refusal guard this note used to describe moved: with
# `late_throttle` costless, a wholesale degradation of the onset derivation
# no longer shows up in THIS floor at all. It is caught instead by the
# `throttle_onset_status` vocabulary assertion and by
# `_assert_onset_is_not_inverted`, both above.
_MIN_COSTED_EVENTS = 20

# MEASURED: median cost 0.176 s, max 0.885 s. The coordinate-frame fix left
# these untouched, as it must (the cost is a corner-TIME gap and never
# touched the onset's distance frame). The 2026-08-06 ruling moved the
# MEDIAN only -- 0.163 -> 0.176 -- and not by changing any cost: it removed
# 55 `late_throttle` rows that were duplicating `over_slowing`'s number, and
# the 16 of them with no `over_slowing` partner sat at the cheap end. The max
# is identical because the costliest corner-lap always had both.
# Catches "costs uniformly 4.9 s" -- which the old body's `<= 5.0` per-event
# bound waved straight through. A median corner-time gap above 1.0 s means
# the driver is losing ~8 s a lap to corner execution against their OWN best
# pass, which is a window/reference defect rather than driving. 1.0 s is
# ~7x the measured median and still far below the 4.9 s mutation.
_MAX_MEDIAN_COST_S = 1.0

# MEASURED: worst cost 0.885 s.
# Catches "every time_cost_s = 0.0", which every other cost assertion here
# waves through (a uniform zero is inside the per-event bounds and drags the
# median DOWN, not up). A session where no corner-lap is even a tenth of a
# second off the driver's own best at that corner does not mean a flawless
# driver -- it means the reference collapsed onto each lap individually, so
# every lap is trivially its own best and the whole comparison is vacuous.
# The plan's own composite-lap figure (0.121 s) is the smallest spread this
# session's geometry can produce. 0.10 s keeps ~9x headroom under 0.885.
_MIN_WORST_COST_S = 0.10

# ── Task 12: the onset floors, TWO-SIDED (fix round 2) ────────────────────
#
# These exist because `late_throttle` shipped for a while on an onset metric
# that was anti-correlated with corner performance: the threshold was THIS
# LAP'S OWN apex speed + 0.5 m/s, so a faster lap had to reach a higher
# ABSOLUTE speed before it tripped and its onset came out LATER. Nothing in
# the gate above could see it -- every count, share, spread and cost bound was
# satisfied while the detector told the driver they were late on throttle
# precisely when they went fast.
#
# ROUND 1 GUARDED ONLY ONE SIDE OF THAT, AND IT WAS THE WRONG ONE TO STOP AT.
# `corr(corner_time, onset)` positive on 8/8 corners looks like the metric
# works, but corr(corner_time, apex_speed) is about -0.95 on this session, so
# ANY onset correlating with apex speed inherits that for free. A metric
# defined as literally `onset := -k * apex_speed` -- carrying no throttle
# information whatsoever -- scored PERFECTLY on every round-1 assertion.
# Hence three floors, not one, and the third is the one that bites.
#
# MEASURED (session-best basis, canonical distance frame): corr(corner_time_s,
# throttle_onset_m) is positive on 6 of 8 corners; the two negatives are
# corner 7 at -0.089 and corner 1 at -0.160, i.e. both indistinguishable from
# zero. BEFORE the per-lap-threshold fix it was NEGATIVE on 6 of 8, and with
# the threshold fixed but the coordinate frame still broken it was 1 of 8.
#
# RE-DERIVED UPWARD, 2 -> 3, by the final review's Critical 1. Removing the
# coordinate-frame artifact from `throttle_onset_m` moved this count from 1 to
# 2 -- sitting EXACTLY on the old bound, i.e. zero headroom, so an equivalent
# session with one more near-zero corner would have failed on nothing. 3 of 8
# still fails instantly on the systemic inversion, which drives 6 of 8
# negative at once; the gap between "2-3 near-zero corners" and "6 inverted
# corners" is the whole discriminating range and it is untouched.
_MAX_NEGATIVELY_CORRELATED_CORNERS = 3

# MEASURED (session-best basis, canonical distance frame): median
# within-corner corr(apex_speed_mps, throttle_onset_m) = -0.572; before the
# threshold fix, +0.552; with the threshold fixed but the frame still broken,
# -0.404. The SIGN is the claim: carrying more apex speed must not push the
# reported onset later. -0.10 sits below the measured -0.572 and far above the
# +0.552 it catches, and deliberately does not pin the strength -- a session
# whose apex speeds barely vary would legitimately correlate weakly.
#
# The eight per-corner values are -0.928, -0.870, -0.808, -0.748, -0.396,
# -0.340, -0.110, +0.004. Their TRUE median is -0.572 (the mean of the two
# middle values). Fix round 2 caught this assertion evaluating
# `sorted(...)[len // 2]` instead, which is the upper-middle value --
# still clearing the floor, but overstating the documented headroom by ~25%.
# `_median` below is now a real median, so the number asserted and the number
# documented are the same number.
_MAX_MEDIAN_APEX_ONSET_CORR = -0.10

# THE UPPER BOUND (fix round 2). Without it, `onset := -k * apex_speed`
# (r = -1.0) satisfies every other assertion here perfectly. An onset that is
# a near-perfect linear function of apex speed is not a throttle measurement,
# it is apex speed rescaled.
#
# MEASURED: 0.572 in the canonical frame, up from 0.404 in the broken one.
# THE FIX MADE THIS WORSE AND THAT IS THE TRUTH, NOT A REGRESSION: the
# coordinate-frame artifact was NOISE that decorrelated the onset from apex
# speed, so removing it exposes how redundant the metric really is. Three of
# the eight corners now exceed |0.80|. The 0.90 bound survives on the median
# with 0.33 of headroom, but the honest reading is that ~33% of the onset's
# within-corner variance is apex speed wearing a different hat. See
# the block below on the REMOVED added-information floor for what is left
# once that redundancy is partialled out -- the short answer is: nothing we
# can distinguish from zero.
_MAX_ABS_APEX_ONSET_CORR = 0.90

# ── THE ADDED-INFORMATION FLOOR WAS REMOVED, NOT LOWERED ─────────────────
#
# There used to be a `_MIN_POOLED_PARTIAL_ONSET_R` here: a floor under the
# partial correlation r(corner_time, onset | apex_speed), asserting that the
# onset says something about corner time that apex speed does not already
# say. It is gone, and this comment is what replaces it, because a floor that
# cannot fail is worse than no floor -- it reads as coverage that is not
# there.
#
# WHY IT CANNOT FAIL. It was set at 0.10 when the measurement was +0.360. The
# +0.360 was mostly a COORDINATE-FRAME ARTIFACT: `throttle_onset_m` was a raw
# per-lap absolute metre differenced across laps whose spans differ by ~20 m,
# and that lap-length term correlates with corner time. In the canonical frame
# the same measurement on the same 71 corner-laps reads:
#
#   specification                      partial r      t
#   pooled, corner z-scored              +0.098      0.81
#   + lap fixed effects                  +0.002      0.02
#   corner-cluster bootstrap 95% CI   [-0.265, +0.233]  (28.6% at or below 0)
#
# The mechanism is confirmed by two independent routes agreeing: the broken
# frame's LAP-FE partial (+0.0989) and the canonical frame's POOLED partial
# (+0.0978) are the same number, because a lap's length offset is to first
# order a lap-level constant that lap dummies already absorbed.
#
# So the honest range for this quantity spans zero. Re-derived downward it
# would have been 0.02 -- a number with 32% of the bootstrap mass BELOW it,
# which on this deterministic fixture passes every single run and therefore
# certifies nothing. Nothing in the mutation battery depended on it either:
# `onset := -k*apex` makes the partial UNDEFINED (caught by the `is not None`
# assertion below, which is real) and a constant onset makes the per-corner
# correlations undefined (caught by the `>= 4 usable corners` assertion).
# Verified by running all 30 mutations with the floor deleted: every one
# still fails the gate.
#
# ⚠ STATED PLAINLY SO NOBODY ASSUMES OTHERWISE: **"the throttle onset carries
# information beyond apex speed" is NOT gate-enforced.** It is measured and
# PRINTED by the acceptance test's diagnostics, so a drift is visible in the
# log, but nothing fails if it goes to zero. That is a deliberate admission
# of what one session with 9 laps per corner can support, not an oversight.
# The 2026-08-06 ruling withdrew the product claim that rested on it
# (`late_throttle` no longer emits a `time_cost_s` and cannot occupy a ranked
# slot alone), so what remains is a measurement kept for the cross-session
# phase, where n can actually answer the question. If a longer session ever
# does establish the signal, THAT is when a floor becomes defensible.
#
# The DEGENERACY assertion below is kept and is not the same thing: it fires
# when the onset is a perfect linear function of apex speed, i.e. when the
# partial is not small but MEANINGLESS. That case is real, reachable, and
# caught.


def _median(values):
    """A real median, averaging the two middle values on an even count.

    `sorted(x)[len(x) // 2]` is the UPPER-MIDDLE value, not the median, and
    with 8 corners that is always the even case. Fix round 2 caught the
    onset-correlation assertion evaluating -0.324 while every comment and the
    report documented the true median -0.404 -- both cleared the floor, so
    nothing failed, but the documented headroom was overstated by ~25%.
    """
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _pearson(xs, ys):
    """Pearson r, or None when it is undefined (too few points, or either
    series constant -- np.corrcoef returns NaN there and a NaN silently
    defeats every comparison it is fed to)."""
    if len(xs) < 3:
        return None
    if np.std(xs) == 0 or np.std(ys) == 0:
        return None
    r = float(np.corrcoef(xs, ys)[0, 1])
    return r if np.isfinite(r) else None


def _pooled_partial_onset_r(by_corner):
    """Partial correlation r(corner_time, onset | apex_speed), pooled across
    every corner-lap after z-scoring each channel WITHIN its own corner.

    Why pooled and not a median of per-corner partials: with 9 laps per
    corner, a per-corner partial carries SE ~ 1/sqrt(9-1-3) = 0.45, so a
    median of eight of them is dominated by noise and ranks candidate onset
    definitions differently from the properly-powered estimate. Z-scoring
    within corner removes every between-corner level difference, which is
    what a per-corner analysis was buying, while keeping n at the number of
    corner-laps.

    Returns ``(r, n)``, or ``(None, n)`` when it is undefined -- notably when
    the onset is a perfect linear function of apex speed, where the partial
    is not merely zero but meaningless, and the caller must treat that as a
    failure rather than as a small number.
    """
    pool_ct, pool_on, pool_ap = [], [], []
    for vals in by_corner.values():
        if len(vals) < 4:
            continue
        for source, dest in zip(zip(*vals), (pool_on, pool_ap, pool_ct)):
            a = np.asarray(source, dtype=float)
            sd = a.std()
            dest.extend((a - a.mean()) / sd if sd > 0 else a - a.mean())

    n = len(pool_ct)
    if n < 8:
        return None, n

    r_ct_on = _pearson(pool_ct, pool_on)
    r_ct_ap = _pearson(pool_ct, pool_ap)
    r_ap_on = _pearson(pool_ap, pool_on)
    if None in (r_ct_on, r_ct_ap, r_ap_on):
        return None, n

    # 1 - r^2 -> 0 exactly when one channel is a linear function of another.
    denom = np.sqrt((1.0 - r_ct_ap ** 2) * (1.0 - r_ap_on ** 2))
    if denom < 1e-3:
        return None, n
    r = float((r_ct_on - r_ct_ap * r_ap_on) / denom)
    return (r if np.isfinite(r) else None), n


def _assert_onset_is_not_inverted(plcm):
    """`throttle_onset_m` must move WITH corner time and AGAINST apex speed.

    See _MAX_NEGATIVELY_CORRELATED_CORNERS / _MAX_MEDIAN_APEX_ONSET_CORR for
    the measured basis. Correlations are computed per corner and only over
    corner-laps whose onset was actually measured -- a refused onset is not a
    late one, and folding it in as a missing value would be a made-up number.
    """
    rows = [m for m in plcm if isinstance(m, dict)]
    by_corner = {}
    for m in rows:
        onset = m.get("throttle_onset_m")
        apex = m.get("apex_speed_mps")
        ctime = m.get("corner_time_s")
        if None in (onset, apex, ctime):
            continue
        if not all(np.isfinite(v) for v in (onset, apex, ctime)):
            continue
        by_corner.setdefault(m.get("corner_id"), []).append((onset, apex, ctime))

    apex_corrs, negative_corners, n_time_corrs = [], [], 0
    for cid, vals in by_corner.items():
        onsets = [v[0] for v in vals]
        apexes = [v[1] for v in vals]
        times = [v[2] for v in vals]
        ra = _pearson(apexes, onsets)
        if ra is not None:
            apex_corrs.append(ra)
        rt = _pearson(times, onsets)
        if rt is not None:
            n_time_corrs += 1
            if rt < 0:
                negative_corners.append((cid, round(rt, 3)))

    # Below this the measurement itself is not meaningful, and silently
    # passing on two corners would be the "assertion that cannot fail" this
    # gate exists to avoid.
    assert n_time_corrs >= 4 and len(apex_corrs) >= 4, (
        f"only {n_time_corrs}/{len(apex_corrs)} corners produced a usable "
        f"onset correlation -- too few to judge the inversion")

    assert len(negative_corners) <= _MAX_NEGATIVELY_CORRELATED_CORNERS, (
        f"corr(corner_time, throttle_onset) is NEGATIVE on "
        f"{len(negative_corners)}/{n_time_corrs} corners {negative_corners} "
        f"-- a SLOWER pass through a corner is being reported with an EARLIER "
        f"throttle onset. That is the pre-2026-08-05 per-lap-threshold "
        f"inversion returning, not driving.")

    median_apex_corr = _median(apex_corrs)
    assert median_apex_corr <= _MAX_MEDIAN_APEX_ONSET_CORR, (
        f"median within-corner corr(apex_speed, throttle_onset) is "
        f"{median_apex_corr:+.3f} (must be <= "
        f"{_MAX_MEDIAN_APEX_ONSET_CORR}) -- carrying more apex speed is "
        f"pushing the reported onset LATER, i.e. the metric is penalising "
        f"the driver for going fast")

    # The OTHER side: not a restatement of apex speed.
    assert abs(median_apex_corr) <= _MAX_ABS_APEX_ONSET_CORR, (
        f"median |corr(apex_speed, throttle_onset)| is "
        f"{abs(median_apex_corr):.3f} (must be <= "
        f"{_MAX_ABS_APEX_ONSET_CORR}) -- the onset has collapsed into a "
        f"rescaling of apex speed and carries no throttle information of "
        f"its own")

    # DEGENERACY only -- there is deliberately NO floor on the value; see
    # "THE ADDED-INFORMATION FLOOR WAS REMOVED, NOT LOWERED" above for why.
    #
    # `None` means the partial is not small but UNDEFINED: one of the three
    # channels is a linear function of another, so "what does the onset add
    # beyond apex speed" has no answer. Exercised by the "corner time
    # collapses onto apex speed" mutation -- the onset-side route to the same
    # degeneracy is caught earlier by `_MAX_ABS_APEX_ONSET_CORR`, which is why
    # this needed a mutation of its own rather than inheriting one.
    pooled_r, n_pooled = _pooled_partial_onset_r(by_corner)
    assert pooled_r is not None, (
        "the onset carries no variance independent of apex speed at all "
        "(its residual after the apex fit is degenerate) -- it is apex "
        "speed under another name")
    return pooled_r, n_pooled


def _assert_driving_events_gate(summary):
    """The gate's assertion body, factored out so it can be replayed against
    deliberately mutated summaries.

    Fix round 1 exists because the previous body could not fail. Keeping the
    assertions callable means the bite-check exercises THE COMMITTED
    ASSERTIONS against each mutation, rather than a hand-copied lookalike
    that can drift from what actually ships. Returns a diagnostics dict for
    the caller to print.
    """
    import driving_events as de
    from pipeline.stages import s01_ingest

    events = summary.get("driving_events") or []
    cap = summary.get("driving_events_capability") or {}
    plcm = summary.get("per_lap_corner_metrics") or []

    # ── the precondition every MEASURED: constant below depends on ────
    # Which reader produced the frame is not a detail: the adapter registry
    # and the legacy io_racechrono fallback hand corner detection different
    # column names, and this same CSV yields 8 corners / 72 corner-laps / 141
    # events down one and 6 / 42 / 93 down the other. Selecting the fallback
    # used to happen silently, on nothing more than whether the launcher had
    # put the repo root on sys.path. Asserted rather than assumed so a run
    # that quietly takes the other path fails HERE, naming the cause, instead
    # of failing an event-count floor that looks like a detector regression.
    #
    # UNCONDITIONAL (fix round 2). This was `if "ingest_path" in summary:`,
    # which meant deleting the key from the orchestrator's copy-through tuple
    # silently disarmed the whole precondition with every test still green --
    # the assertion could not fail, which is the one property this gate exists
    # to never have.
    assert summary.get("ingest_path") == s01_ingest.INGEST_PATH_ADAPTER, (
        f"ingested via {summary.get('ingest_path')!r}, not the adapter "
        f"registry -- every floor in this gate was measured on the adapter "
        f"path (which is what production runs), so none of them applies to "
        f"this run")

    # ── the denominator ───────────────────────────────────────────────
    corner_laps = {(m.get("lap_number"), m.get("corner_id"))
                   for m in plcm if isinstance(m, dict)}
    assert len(corner_laps) >= _MIN_CORNER_LAPS, (
        f"only {len(corner_laps)} corner-laps reached the detectors "
        f"(floor {_MIN_CORNER_LAPS}); "
        f"{len({c for _, c in corner_laps})} corners x "
        f"{len({lap for lap, _ in corner_laps})} laps")

    # ── Task 12: the onset derivation ran, and named every refusal ────
    # Wiring AND vocabulary in one assertion: a corner-lap with no status at
    # all means `_assign_throttle_onsets` never reached it (late_throttle
    # would silently read "insufficient" for that lap), and a status outside
    # the closed set means some caller invented a reason string.
    statuses = Counter(m.get("throttle_onset_status")
                       for m in plcm if isinstance(m, dict))
    stray = {s: n for s, n in statuses.items() if s not in de.ONSET_STATUSES}
    assert not stray, (
        f"{sum(stray.values())} corner-laps carry no / an unknown "
        f"throttle_onset_status: {stray}")

    # ── Task 12: the onset metric is not anti-correlated with pace ────
    # Returns the pooled partial for DIAGNOSTICS ONLY -- it is observed and
    # printed, never asserted on. See the block comment where the floor used
    # to be.
    onset_partial = _assert_onset_is_not_inverted(plcm)

    # ── events exist, in quantity ─────────────────────────────────────
    assert events, "no driving events produced on real telemetry"
    assert len(events) >= _MIN_EVENTS, (
        f"only {len(events)} events over {len(corner_laps)} corner-laps "
        f"(floor {_MIN_EVENTS})")

    # ── the capability record: KEYS *and* VALUES ──────────────────────
    # The old body asserted only set(cap), which run_registry populates
    # unconditionally for every registered detector -- so it could never
    # observe a degraded value. The values are the part that carries
    # information.
    assert set(cap) == {"over_slowing", "late_throttle",
                        "re_braking", "envelope_under_use"}, cap
    assert all(v == de.CAPABILITY_DETECTED for v in cap.values()), (
        f"every detector must actually fire on this fixture, got {cap}")

    # ── all four detectors are represented in the events themselves ───
    types = {e.event_type for e in events}
    assert types == set(de.EVENT_TYPES), (
        f"expected all four detectors to emit, got {sorted(types)}")

    # ── honesty: the headline "everything is measured" claim ──────────
    n_measured = sum(1 for e in events if e.validity == de.VALIDITY_MEASURED)
    share = n_measured / len(events)
    assert share >= _MIN_MEASURED_SHARE, (
        f"only {n_measured}/{len(events)} = {share:.1%} of events are "
        f"'{de.VALIDITY_MEASURED}' (floor {_MIN_MEASURED_SHARE:.0%}); "
        f"validity mix {Counter(e.validity for e in events)}")

    # ── spread: not all one corner, not all one lap ───────────────────
    laps = {e.lap_number for e in events}
    corner_ids = {e.corner_id for e in events}
    assert len(laps) >= _MIN_DISTINCT_LAPS, f"events on only {len(laps)} laps: {laps}"
    assert len(corner_ids) >= _MIN_DISTINCT_CORNERS, (
        f"events on only {len(corner_ids)} corners: {sorted(corner_ids)} -- "
        f"a session's problems are not all in one place")

    # ── no duplicates ─────────────────────────────────────────────────
    # Each detector emits at most one event per window and windows are
    # unique per (lap, corner), so this is a structural invariant. It is
    # also the regression guard for Task 10's dedupe.
    keys = [(e.event_type, e.lap_number, e.corner_id) for e in events]
    assert len(set(keys)) == len(keys), (
        f"{len(keys) - len(set(keys))} duplicate (type, lap, corner) events")

    # ── per-event structure ───────────────────────────────────────────
    costs = []
    for e in events:
        # NOTE: these two are defence-in-depth, NOT teeth. DrivingEvent.
        # __post_init__ already raises on a bad event_type or validity and
        # run_registry swallows the construction failure, so a violating
        # event can never reach this loop. Kept because they are free and
        # would catch a future refactor that moves validation out of the
        # dataclass; do not mistake them for the assertions that bite.
        assert e.event_type in de.EVENT_TYPES
        assert e.validity in de.VALIDITIES

        # Spans must be real and ordered. Catches every span collapsing to
        # 0.0, which would make Phase 3 render every event at the start line.
        assert 0.0 <= e.s_norm_start < e.s_norm_end <= 1.0, (
            f"degenerate span [{e.s_norm_start}, {e.s_norm_end}] "
            f"(lap {e.lap_number} corner {e.corner_id})")

        if e.validity == de.VALIDITY_MEASURED:
            assert e.evidence, "a measured event must carry evidence"

            # Magnitude must clear the detector's own emission floor -- the
            # detector only emits ABOVE it, so this is structural. Catches
            # every magnitude being zeroed.
            if e.event_type == "over_slowing":
                assert e.magnitude > de.OVER_SLOWING_APEX_DEFICIT_FLOOR_MPS, (
                    f"over_slowing magnitude {e.magnitude} at or below its "
                    f"own emission floor")
            elif e.event_type == "late_throttle":
                assert e.magnitude > de.LATE_THROTTLE_ONSET_FLOOR_M, (
                    f"late_throttle magnitude {e.magnitude} at or below its "
                    f"own emission floor")

            if e.time_cost_s is not None:
                # Lower bound is an INVARIANT, not a taste: the reference
                # corner time is the minimum over admissible laps and is
                # self-inclusive (this window's own time is one of the
                # candidates -- see s10d3_driving_events' module docstring),
                # so the gap can never be negative. The old body's -0.5
                # tolerance let a uniformly-negative mutation pass.
                assert -1e-9 <= e.time_cost_s <= 5.0, (
                    f"implausible cost {e.time_cost_s}s "
                    f"(lap {e.lap_number} corner {e.corner_id})")
                costs.append(e.time_cost_s)

    # ── the ranking key actually exists and is plausible in bulk ──────
    assert len(costs) >= _MIN_COSTED_EVENTS, (
        f"only {len(costs)} of {len(events)} events carry a time_cost_s "
        f"(floor {_MIN_COSTED_EVENTS}) -- the ranked view has nothing to rank")
    median_cost = _median(costs)
    assert median_cost <= _MAX_MEDIAN_COST_S, (
        f"median corner-time gap {median_cost:.3f}s exceeds "
        f"{_MAX_MEDIAN_COST_S}s -- that is a window/reference defect, "
        f"not driving")
    assert max(costs) >= _MIN_WORST_COST_S, (
        f"worst corner-time gap is only {max(costs):.3f}s (floor "
        f"{_MIN_WORST_COST_S}s) -- the per-corner reference has collapsed "
        f"onto each lap individually, making every comparison vacuous")

    return {
        "corner_laps": corner_laps, "events": events, "cap": cap,
        "costs": sorted(costs), "measured_share": share,
        "laps": laps, "corner_ids": corner_ids,
        "onset_partial": onset_partial,
    }


@pytest.fixture(scope="module")
def _real_summary(tmp_path_factory):
    """Run the real pipeline ONCE for this module.

    Module-scoped because it costs minutes, and the mutation battery below
    replays two dozen deliberately degraded copies of its output against the
    SHIPPED gate helper -- re-running the pipeline per mutation would turn a
    4-minute test into an hour.

    Track-registry isolation is done by hand rather than through
    `_isolated_track_registry` only because that fixture is function-scoped
    (it uses tmp_path/monkeypatch) and pytest forbids a module-scoped fixture
    from depending on one. Same effect and same reason: keep the pipeline's
    track-registration write off the tracked models/tracks.json. Restored in
    a `finally` so a pipeline failure cannot leak the patch into later tests.
    """
    if not os.path.exists(_REAL_CSV):
        pytest.skip("real fixture absent")

    import track_detection
    from pipeline import run_full_analysis

    fake_path = tmp_path_factory.mktemp("tracks") / "tracks_isolated.json"
    original = track_detection._default_db_path
    track_detection._default_db_path = lambda: fake_path
    try:
        return run_full_analysis(_REAL_CSV, {})
    finally:
        track_detection._default_db_path = original


@pytest.mark.skipif(not os.path.exists(_REAL_CSV), reason="real fixture absent")
def test_driving_events_on_real_kart_telemetry(_real_summary):
    """Acceptance: events are emitted in quantity, all four detectors fire,
    every event is measured, located and non-degenerate, and the costs are
    plausible both per-event and in bulk.

    MEASURED on this fixture: 72 corner-laps (9 laps x 8 corners), 140
    events, 88.6% validity="measured", all four capability values "detected",
    44 costed events, costs min 0.000 / median 0.176 / max 0.885 s. Event mix
    over_slowing 44 / late_throttle 56 / envelope_under_use 35 (20 measured +
    15 refused on a tier-2 anchor) / re_braking 5.

    THE FINAL REVIEW MOVED THESE NUMBERS TWICE, both times by refusing to
    make a claim the data does not support:
      * the coordinate-frame fix (Critical 1) put `throttle_onset_m` in
        `distance_norm`, dropping late_throttle 58 -> 56 and its largest
        magnitude 41.20 -> 28.89 m -- 12.31 m of that headline example was
        LAP LENGTH. Per-corner medians fell 34-42% at corners 3, 6 and 8.
      * the tier-2 ruling (IMPORTANT 1b) turned 14 measured
        `envelope_under_use` events into 15 `not_measurable` ones, because
        on a `driver_best_session` anchor the 100% floor cannot be exceeded
        and the detector was reporting arithmetic as measurement.
    Costs are untouched by both (max 0.885 s) and must be: the cost is a
    corner-TIME gap and never touched either mechanism.

    A THIRD change, the 2026-08-06 ruling, removed `late_throttle`'s
    `time_cost_s` entirely -- it was `over_slowing`'s own number for the same
    corner-lap, and this detector's added information beyond apex speed is
    +0.098 (t = 0.81), not distinguishable from zero. Costed events 99 -> 44,
    median 0.163 -> 0.176 s (composition only: the removed rows were
    duplicates, and the 16 with no `over_slowing` partner sat at the cheap
    end). Event COUNT, capability and measured share are all unchanged -- the
    measurement still ships, only the claim was withdrawn.

    THE PRECONDITION THESE CONSTANTS CARRY (fix round 2). Every number above
    holds only for the ADAPTER-REGISTRY ingestion path, which is what
    production runs (`Dockerfile`: `PYTHONPATH=/app:/app/telemetry_tool`) and
    what the gate asserts below. The legacy `io_racechrono` fallback path
    hands corner detection differently-named columns and yields 6 corners /
    42 corner-laps / 93 events on this same file -- so a run down that path
    would fail these floors for a reason that has nothing to do with driving
    events. `s01_ingest._ensure_package_root_on_path` now makes the adapter
    path reachable from any launcher, and the `ingest_path` assertion below
    fails loudly rather than silently re-baselining if it is ever not taken.

    TASK 12 moved these numbers. Fixing `throttle_onset_m`'s per-lap
    threshold (see s10b_corners._assign_throttle_onsets) changed the
    late_throttle count 59 -> 58 (57 measured + 1 honest `not_measurable`),
    events 142 -> 141, costed events 103 -> 101, and the cost median
    0.138 -> 0.163 s. No floor was weakened: every one still clears its bound
    by the same order of magnitude it was set with. The event mix is
    over_slowing 44, late_throttle 58, envelope_under_use 34, re_braking 5.

    THE PROBE BASELINE, CORRECTED (fix round 1). The plan quotes
    "over_slowing 57%, late_throttle 68%, re_braking 7%" from
    `original_probe.py` variant C. Re-running that probe shows two of those
    three cannot be compared to this stage as-is:

      * `re_braking` was NEVER MEASURED by the probe. It gates on
        `if "accel_long_mps2" in lap.columns`, a pipeline-internal name that
        does not exist on the probe's raw-CSV frame (which carries
        `Longitudinal acceleration (G) *calc`), so its counter stayed 0 and
        the probe reports 0/54 = 0% in all three variants. The plan's "7%"
        came from a later note measuring the pipeline's own 8-corner
        windows, so agreeing with it is circular, not corroboration.
      * `over_slowing` (54) and `late_throttle` (40) are percentages of
        DIFFERENT denominators -- the probe divides late_throttle only by
        the windows where its onset proxy resolved.

    Restricted to the six corners the probe also found, this stage measures
    over_slowing 31/54 -- the probe's exact numerator AND denominator. So
    over_slowing's divergence is explained entirely by the two extra corners
    (ids 3 and 8) the pipeline detects and the probe did not; the probe
    feeds `detect_corners` a differently-preprocessed frame.
    `late_throttle` is NOT explained that way (45/54 here vs 27/54) and has
    a second, independent cause -- the two onset derivations differ. See the
    Task 11 report. Do not "fix" any of this by moving a threshold.

    `summary["driving_events"]` carries `driving_events.DrivingEvent`
    dataclass instances, not dicts: `orchestrator.py` assigns
    `run_driving_events(...)["events"]` straight through, and that is
    `run_registry`'s `list[DrivingEvent]`. Hence attribute access.
    """
    from pipeline.stages import s01_ingest

    summary = _real_summary

    # The precondition, asserted on the REAL summary before the gate runs:
    # the key must be PRESENT (not merely non-contradictory) and must name the
    # adapter path. `_assert_driving_events_gate` re-checks it, but this
    # catches the orchestrator silently dropping the key, which would make the
    # gate's own check vacuous for every mutated replay too.
    assert "ingest_path" in summary, (
        "the pipeline summary no longer reports which reader ingested the "
        "file -- every MEASURED constant in this module is conditioned on "
        "that and can no longer be checked")
    assert summary["ingest_path"] == s01_ingest.INGEST_PATH_ADAPTER

    d = _assert_driving_events_gate(summary)

    cl = d["corner_laps"]
    print(f"\ncorner-laps: {len(cl)} "
          f"({len({lap for lap, _ in cl})} laps x "
          f"{len({c for _, c in cl})} corners)")
    print(f"event types: {Counter(e.event_type for e in d['events'])}")
    print(f"capability:  {d['cap']}")
    print(f"measured:    {d['measured_share']:.1%} of {len(d['events'])} events")
    costs = d["costs"]
    print(f"cost s: min {costs[0]:.3f} median "
          f"{costs[len(costs) // 2]:.3f} max {costs[-1]:.3f}")
    r, n = d["onset_partial"]
    print(f"onset partial r(corner_time, onset | apex) = {r:+.3f} over {n} "
          f"corner-laps  [OBSERVED, NOT ASSERTED -- see the removed floor]")
    print("onset status: "
          f"{Counter(m.get('throttle_onset_status') for m in summary['per_lap_corner_metrics'])}")


# ══════════════════════════════════════════════════════════════════
# Task 12 — the mutation battery. A bite-check, made permanent.
# ══════════════════════════════════════════════════════════════════
#
# A gate is only worth its runtime if it can FAIL. Fix round 1 found that the
# original body caught 1 of 16 deliberate degradations, and rewrote it; a
# later review re-verified the rewrite by replaying mutations by hand -- but
# that battery lived in a scratch script, so nothing in the repo stopped the
# gate being hollowed out again. This is that battery, committed.
#
# Each entry below takes the REAL pipeline summary and returns one
# deliberately degraded copy that a functioning gate MUST reject. They are
# replayed against `_assert_driving_events_gate` itself, not a copy of it, so
# they exercise exactly the assertions that ship.
#
# DELIBERATELY NOT INCLUDED: the calibration probes that sit exactly ON a
# floor by construction (31 events against a floor of 30, events on exactly 4
# corners against a floor of 4, costs at 0.99 s against a 1.0 s bound). Those
# measure where the gate's edge is, which is a review question; asserting they
# pass would freeze the floors against ever being tightened, and asserting
# they fail would be asserting something false.


def _replace(event, **kw):
    """`dataclasses.replace`, which RE-RUNS `__post_init__` -- so a mutation
    built this way is one the record itself considers structurally legal."""
    import dataclasses

    return dataclasses.replace(event, **kw)


def _force(event, **kw):
    """Mutate a frozen event BYPASSING `__post_init__` -- models the world
    where validation has been moved out of the dataclass, which is the only
    world in which the gate's own per-event checks have to do the work."""
    import copy

    clone = copy.copy(event)
    for k, v in kw.items():
        object.__setattr__(clone, k, v)
    return clone


def _summary_with(base, *, events=None, cap=None, plcm=None, ingest_path=-1):
    """A mutated copy of the real summary.

    `ingest_path` is carried through by default (fix round 2): without it every
    mutated summary lacked the key, so the gate's own precondition assertion
    was never exercised by the battery and could be disarmed unnoticed. Pass
    it explicitly to mutate it; the `-1` sentinel distinguishes "not given"
    from an explicit `None`.
    """
    return {
        "driving_events": base["driving_events"] if events is None else events,
        "driving_events_capability": (
            base["driving_events_capability"] if cap is None else cap),
        "per_lap_corner_metrics": (
            base["per_lap_corner_metrics"] if plcm is None else plcm),
        "ingest_path": (base.get("ingest_path") if ingest_path == -1
                        else ingest_path),
    }


def _all_on_one_corner(base):
    """Every event moved to corner 1, keeping (type, lap, corner) unique so
    the duplicate check cannot fire first and mask the spread check."""
    out, seen = [], set()
    for i, e in enumerate(base["driving_events"]):
        if (e.event_type, e.lap_number, 1) in seen:
            out.append(_replace(e, corner_id=1, lap_number=100 + i))
            seen.add((e.event_type, 100 + i, 1))
        else:
            out.append(_replace(e, corner_id=1))
            seen.add((e.event_type, e.lap_number, 1))
    return out


def _onset_sign_flipped(base):
    """Reproduce the pre-2026-08-05 inversion's SIGNATURE exactly: within
    each corner, replace every onset with (C - onset). A pure reflection
    leaves the spread untouched and flips both correlations' signs, so this
    mutation degrades nothing the rest of the gate can see -- which is the
    entire point, since nothing else in the gate could see the real defect
    either."""
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    peak = {}
    for m in rows:
        v = m.get("throttle_onset_m")
        if v is not None:
            peak[m["corner_id"]] = max(peak.get(m["corner_id"], 0.0), v)
    for m in rows:
        v = m.get("throttle_onset_m")
        if v is not None:
            m["throttle_onset_m"] = 2 * peak[m["corner_id"]] - v
    return rows


def _flip_share(base, every):
    """Flip every `every`-th event to a non-measured validity.

    `insufficient_samples` until the final review removed it (no producer
    could emit it); `not_measurable` is the surviving non-measured value and
    degrades the measured SHARE identically, which is what this mutation
    exists to test.
    """
    import driving_events as de

    return [
        _replace(e, validity=de.VALIDITY_NOT_MEASURABLE,
                 magnitude=None, time_cost_s=None) if i % every == 0 else e
        for i, e in enumerate(base["driving_events"])
    ]


def _measured_only(base, de, **kw):
    """Apply `kw` to the measured events only, leaving `not_measurable` ones
    untouched -- they are structurally forbidden from carrying magnitudes or
    costs, so mutating them would raise out of the record instead of testing
    the gate."""
    return [_replace(e, **kw) if e.validity == de.VALIDITY_MEASURED else e
            for e in base["driving_events"]]


def _one_of_each_type(base):
    import driving_events as de

    return [next(e for e in base["driving_events"] if e.event_type == t)
            for t in sorted(de.EVENT_TYPES)]


def _strip_onset_status(base):
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    for m in rows:
        m.pop("throttle_onset_status", None)
    return rows


def _invented_onset_status(base):
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    for m in rows:
        m["throttle_onset_status"] = "ok"
    return rows


def _onset_is_apex_rescaled(base):
    """`onset := C - k * apex_speed`. The mutation round 1's gate structurally
    could not catch: it scores PERFECTLY on "corr(corner_time, onset) positive
    on every corner" and on "median corr(apex, onset) is negative", because
    corr(corner_time, apex) ~ -0.95 hands it both for free. It carries no
    throttle information whatsoever -- it is apex speed with a minus sign."""
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    for m in rows:
        apex = m.get("apex_speed_mps")
        if apex is not None and m.get("throttle_onset_m") is not None:
            m["throttle_onset_m"] = 500.0 - 10.0 * float(apex)
    return rows


def _corner_time_is_apex_rescaled(base):
    """`corner_time := a - b * apex_speed`, exactly, within each corner.

    The ONLY mutation that reaches the partial-correlation DEGENERACY
    assertion. Everything else that could make that partial undefined is
    caught earlier: an onset that is a linear function of apex speed trips
    `_MAX_ABS_APEX_ONSET_CORR` (median |r| = 1.000), and a constant onset
    trips the "too few usable corners" check. Verified by driving the shipped
    gate helper against each mutation and reading which assertion fired.

    This one degenerates the OTHER leg: if corner time IS apex speed, then
    "what does the onset add BEYOND apex speed" has no answer -- the residual
    it would be measured against is zero. That is a real upstream collapse
    (two independent measurements landing on one another), and without this
    mutation the `pooled_r is not None` assertion was never exercised by
    anything.
    """
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    for m in rows:
        apex = m.get("apex_speed_mps")
        if apex is not None and m.get("corner_time_s") is not None:
            m["corner_time_s"] = 40.0 - 2.0 * float(apex)
    return rows


def _constant_onset(base):
    rows = [dict(m) for m in base["per_lap_corner_metrics"]]
    for m in rows:
        if m.get("throttle_onset_m") is not None:
            m["throttle_onset_m"] = 100.0
    return rows


# name -> builder(real summary) -> mutated summary. Kept as a dict of
# callables rather than pre-built objects because the real summary only
# exists once the module-scoped fixture has run.
_MUTATIONS = {
    # ── wholesale validity flips ──────────────────────────────────────
    "every event non-measured (structurally legal form)":
        lambda b, de: _summary_with(b, events=[
            _replace(e, validity=de.VALIDITY_NOT_MEASURABLE,
                     magnitude=None, time_cost_s=None)
            for e in b["driving_events"]]),
    "every event non-measured (magnitudes kept, post_init bypassed)":
        lambda b, de: _summary_with(b, events=[
            _force(e, validity=de.VALIDITY_NOT_MEASURABLE)
            for e in b["driving_events"]]),
    "every event not_measurable":
        lambda b, de: _summary_with(b, events=[
            _replace(e, validity=de.VALIDITY_NOT_MEASURABLE,
                     magnitude=None, time_cost_s=None)
            for e in b["driving_events"]]),
    "half the events flipped to insufficient (50% measured)":
        lambda b, de: _summary_with(b, events=_flip_share(b, 2)),
    "a quarter flipped to insufficient (75% measured)":
        lambda b, de: _summary_with(b, events=_flip_share(b, 4)),

    # ── the ranking key ───────────────────────────────────────────────
    # `_measured_only` on these two: a `not_measurable` event may not carry
    # numbers at all (DrivingEvent.__post_init__), so setting one on it would
    # raise ValueError from the record rather than exercise the gate. The
    # fixture grew its first real not_measurable event when the onset basis
    # changed in fix round 2 -- these mutations degrade what CAN legally be
    # degraded.
    "every time_cost_s = 0.0":
        lambda b, de: _summary_with(b, events=_measured_only(
            b, de, time_cost_s=0.0)),
    "every time_cost_s = None":
        lambda b, de: _summary_with(b, events=[
            _replace(e, time_cost_s=None) for e in b["driving_events"]]),
    "costs uniformly 4.9 s":
        lambda b, de: _summary_with(b, events=[
            _replace(e, time_cost_s=4.9) if e.time_cost_s is not None else e
            for e in b["driving_events"]]),
    "costs uniformly -0.4 s":
        lambda b, de: _summary_with(b, events=[
            _replace(e, time_cost_s=-0.4) if e.time_cost_s is not None else e
            for e in b["driving_events"]]),

    # ── spread and quantity ───────────────────────────────────────────
    "no events at all":
        lambda b, de: _summary_with(b, events=[], cap={}),
    "events collapse to one per detector":
        lambda b, de: _summary_with(b, events=_one_of_each_type(b)),
    "all events from ONE corner (keys kept unique)":
        lambda b, de: _summary_with(b, events=_all_on_one_corner(b)),
    "all events from ONE corner (naive, duplicates)":
        lambda b, de: _summary_with(b, events=[
            _replace(e, corner_id=1) for e in b["driving_events"]]),
    "events on only 3 corners":
        lambda b, de: _summary_with(b, events=[
            e for e in b["driving_events"] if e.corner_id in (1, 2, 3)]),
    "corner detection regresses 8 -> 2":
        lambda b, de: _summary_with(
            b,
            plcm=[m for m in b["per_lap_corner_metrics"]
                  if m.get("corner_id") in (1, 2)],
            events=[e for e in b["driving_events"] if e.corner_id in (1, 2)]),
    "Task 10 dedupe regressed (every event 5x)":
        lambda b, de: _summary_with(b, events=b["driving_events"] * 5),

    # ── detectors and the capability record ───────────────────────────
    "only one detector fires (over_slowing)":
        lambda b, de: _summary_with(b, events=[
            e for e in b["driving_events"] if e.event_type == "over_slowing"]),
    "re_braking silenced (3 of 4 detectors fire)":
        lambda b, de: _summary_with(b, events=[
            e for e in b["driving_events"] if e.event_type != "re_braking"]),
    "all capability values = insufficient":
        lambda b, de: _summary_with(b, cap={
            k: de.CAPABILITY_INSUFFICIENT
            for k in b["driving_events_capability"]}),
    "all capability values = not_triggered":
        lambda b, de: _summary_with(b, cap={
            k: de.CAPABILITY_NOT_TRIGGERED
            for k in b["driving_events_capability"]}),
    "ONE capability degraded (re_braking insufficient)":
        lambda b, de: _summary_with(b, cap={
            **b["driving_events_capability"],
            "re_braking": de.CAPABILITY_INSUFFICIENT}),

    # ── per-event structure ───────────────────────────────────────────
    "every magnitude = 0.0":
        lambda b, de: _summary_with(b, events=_measured_only(
            b, de, magnitude=0.0)),
    "every span collapsed to 0.0":
        lambda b, de: _summary_with(b, events=[
            _replace(e, s_norm_start=0.0, s_norm_end=0.0)
            for e in b["driving_events"]]),

    # ── Task 12: the throttle-onset derivation ────────────────────────
    "the onset inversion returns (sign of both correlations flipped)":
        lambda b, de: _summary_with(b, plcm=_onset_sign_flipped(b)),
    # ── the precondition itself ───────────────────────────────────────
    "ingested via the legacy reader, not the adapter registry":
        lambda b, de: _summary_with(b, ingest_path="legacy_racechrono"),
    "ingest_path missing entirely (orchestrator stopped copying it)":
        lambda b, de: _summary_with(b, ingest_path=None),

    "onset is a pure rescaling of apex speed (no throttle information)":
        lambda b, de: _summary_with(b, plcm=_onset_is_apex_rescaled(b)),
    "corner time collapses onto apex speed (the partial is undefined)":
        lambda b, de: _summary_with(b, plcm=_corner_time_is_apex_rescaled(b)),
    "onset stops discriminating (one constant per corner)":
        lambda b, de: _summary_with(b, plcm=_constant_onset(b)),
    "throttle_onset_status never written (second pass unwired)":
        lambda b, de: _summary_with(b, plcm=_strip_onset_status(b)),
    "throttle_onset_status invented outside the vocabulary":
        lambda b, de: _summary_with(b, plcm=_invented_onset_status(b)),
}


@pytest.mark.skipif(not os.path.exists(_REAL_CSV), reason="real fixture absent")
@pytest.mark.parametrize("mutation", sorted(_MUTATIONS))
def test_the_real_data_gate_rejects_each_deliberate_degradation(
    mutation, _real_summary,
):
    """Every mutation must make the SHIPPED gate helper raise.

    A green here is a failure report: it names a degradation the gate would
    ship without noticing.
    """
    import driving_events as de

    base = {
        "driving_events": _real_summary.get("driving_events") or [],
        "driving_events_capability": (
            _real_summary.get("driving_events_capability") or {}),
        "per_lap_corner_metrics": (
            _real_summary.get("per_lap_corner_metrics") or []),
        "ingest_path": _real_summary.get("ingest_path"),
    }
    mutated = _MUTATIONS[mutation](base, de)

    with pytest.raises(AssertionError):
        _assert_driving_events_gate(mutated)
