"""The meter's live lane: newest sample only, never stale, never blocks the durable lane."""

from datetime import datetime, timedelta

import pytest
import requests

import db
import sync
from config import TZ


class FakeSession:
    def __init__(self, status=200, fail=False):
        self.posts, self.status, self.fail = [], status, fail

    def post(self, url, json, headers, timeout):
        if self.fail:
            raise requests.ConnectionError("down")
        self.posts.append(json)
        return type("R", (), {"status_code": self.status})()


@pytest.fixture(autouse=True)
def fresh():
    with db.connect() as conn:
        conn.executescript("DROP TABLE IF EXISTS power_data;")
    db.init_db()


def add_sample(age_s=0.0):
    ts = (datetime.now(TZ) - timedelta(seconds=age_s)).isoformat(timespec="milliseconds")
    db.insert_samples([{"phase": p, "voltage_rms": 230.0, "active_power": 100.0, "timestamp": ts}
                       for p in ("R", "Y", "B", "Neutral")])


def test_pushes_newest_sample_once():
    lane = sync.LiveLane()
    lane.session = FakeSession()
    add_sample(age_s=1)
    add_sample()
    assert lane.push_once() is True
    assert len(lane.session.posts) == 1 and len(lane.session.posts[0]) == 4  # one sample, all phases
    assert all("id" not in r for r in lane.session.posts[0])
    assert lane.push_once() is None  # nothing new -> nothing sent


def test_never_pushes_stale_data():
    lane = sync.LiveLane()
    lane.session = FakeSession()
    add_sample(age_s=60)  # sampler stopped a minute ago
    assert lane.push_once() is None and lane.session.posts == []


def test_failure_is_quiet_and_recovers():
    lane = sync.LiveLane()
    lane.session = FakeSession(fail=True)
    add_sample()
    assert lane.push_once() is False and lane.failing
    lane.session = FakeSession()
    assert lane.push_once() is True and not lane.failing  # same sample retried once the server is back


def test_live_lane_never_marks_rows_synced():
    lane = sync.LiveLane()
    lane.session = FakeSession()
    add_sample()
    lane.push_once()
    assert db.count_unsynced() == 4  # the durable lane still owns delivery
