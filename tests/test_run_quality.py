"""Tests du plan de synchronisation des anomalies (sans base de donnees)."""
from hub.run_quality import RULE_CODES, plan_sync
from hub.quality_rules import detect_all, QualityData


def test_new_anomaly_is_inserted():
    plan = plan_sync({}, {("r", "1")})
    assert plan.to_insert == [("r", "1")]
    assert plan.to_touch == plan.to_reopen == plan.to_fix == []


def test_known_open_anomaly_is_only_touched():
    plan = plan_sync({("r", "1"): "open"}, {("r", "1")})
    assert plan.to_touch == [("r", "1")]
    assert plan.to_insert == plan.to_fix == []


def test_accepted_anomaly_stays_accepted_while_detected():
    plan = plan_sync({("r", "1"): "accepted"}, {("r", "1")})
    assert plan.to_touch == [("r", "1")]
    assert plan.to_reopen == []


def test_fixed_anomaly_that_comes_back_is_reopened():
    plan = plan_sync({("r", "1"): "fixed"}, {("r", "1")})
    assert plan.to_reopen == [("r", "1")]
    assert plan.to_insert == plan.to_touch == []


def test_open_or_accepted_anomaly_that_disappears_is_fixed():
    existing = {("r", "1"): "open", ("r", "2"): "accepted", ("r", "3"): "fixed"}
    plan = plan_sync(existing, set())
    assert plan.to_fix == [("r", "1"), ("r", "2")]


def test_empty_everything():
    plan = plan_sync({}, set())
    assert plan.to_insert == plan.to_touch == plan.to_reopen == plan.to_fix == []


def test_rule_codes_are_unique_and_cover_all_rules():
    assert len(RULE_CODES) == len(set(RULE_CODES)) == 7
    assert detect_all(QualityData()) == []