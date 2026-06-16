from __future__ import annotations

from datetime import datetime, timezone

from decisioning.champion_challenger import (
    CCDecisionRecord,
    CCDecisionStore,
    ChampionChallengerRouter,
    ModelConfig,
)


def test_shadow_mode_returns_champion_decision() -> None:
    store = CCDecisionStore(db_url="sqlite+pysqlite:///:memory:")
    champ = ModelConfig(role="CHAMPION", model_registry_name="cc_pd", model_version="v1", traffic_pct=1.0)
    chall = ModelConfig(role="CHALLENGER", model_registry_name="cc_pd", model_version="v2", traffic_pct=0.0)

    router = ChampionChallengerRouter(champion=champ, challenger=chall, store=store, random_seed=42)

    def score_fn(features, model_version: str):
        return {
            "pd_score": 0.02 if model_version == "v1" else 0.03,
            "decision": "APPROVE",
            "credit_limit": 5000,
            "apr": 19.99,
        }

    rec = router.run_both_shadow("app_1", {"x": 1}, score_fn)
    assert rec.role == "CHAMPION"
    assert rec.model_version == "v1"
    assert rec.is_shadow is False


def test_live_split_routing_is_deterministic() -> None:
    store = CCDecisionStore(db_url="sqlite+pysqlite:///:memory:")
    champ = ModelConfig(role="CHAMPION", model_registry_name="cc_pd", model_version="v1", traffic_pct=1.0)
    chall = ModelConfig(role="CHALLENGER", model_registry_name="cc_pd", model_version="v2", traffic_pct=0.5)

    router = ChampionChallengerRouter(champion=champ, challenger=chall, store=store, random_seed=123)
    assert router.route("same_app") == router.route("same_app")


def test_comparison_report_promote_logic() -> None:
    store = CCDecisionStore(db_url="sqlite+pysqlite:///:memory:")
    now = datetime.now(timezone.utc)

    # Champion: 50% approval, mean PD 0.05
    for i in range(100):
        store.add(
            CCDecisionRecord(
                application_id=f"c{i}",
                timestamp=now,
                role="CHAMPION",
                model_version="v1",
                pd_score=0.05,
                decision="APPROVE" if i < 50 else "DECLINE",
                credit_limit=None,
                apr=None,
                is_shadow=False,
            )
        )

    # Challenger: 52% approval (within ±3pp), mean PD 0.052 (<= 1.05×0.05)
    for i in range(100):
        store.add(
            CCDecisionRecord(
                application_id=f"d{i}",
                timestamp=now,
                role="CHALLENGER",
                model_version="v2",
                pd_score=0.052,
                decision="APPROVE" if i < 52 else "DECLINE",
                credit_limit=None,
                apr=None,
                is_shadow=True,
            )
        )

    report = store.generate_comparison_report(lookback_days=7)
    assert report.recommendation == "PROMOTE"


def test_reject_logic() -> None:
    store = CCDecisionStore(db_url="sqlite+pysqlite:///:memory:")
    now = datetime.now(timezone.utc)

    # Champion: 50% approval, mean PD 0.05
    for i in range(100):
        store.add(
            CCDecisionRecord(
                application_id=f"c{i}",
                timestamp=now,
                role="CHAMPION",
                model_version="v1",
                pd_score=0.05,
                decision="APPROVE" if i < 50 else "DECLINE",
                credit_limit=None,
                apr=None,
                is_shadow=False,
            )
        )

    # Challenger: 60% approval (+10pp), mean PD 0.06 (+20%)
    for i in range(100):
        store.add(
            CCDecisionRecord(
                application_id=f"d{i}",
                timestamp=now,
                role="CHALLENGER",
                model_version="v2",
                pd_score=0.06,
                decision="APPROVE" if i < 60 else "DECLINE",
                credit_limit=None,
                apr=None,
                is_shadow=True,
            )
        )

    report = store.generate_comparison_report(lookback_days=7)
    assert report.recommendation == "REJECT"
