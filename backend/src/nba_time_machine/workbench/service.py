"""Operator-only, as-of inspection using the canonical database and scoring code."""
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from urllib.parse import quote

from pydantic import ValidationError
from sqlalchemy import func, select

from nba_time_machine.db import (
    GameObservationRecord, GameRecord, RecommendationScoreRecord, SeasonRecord,
    SourceRecord, SportsExternalIdentityRecord, TeamRecord, TemporalFactRecord,
)
from nba_time_machine.ranking.morning_features import FEATURE_VERSION
from nba_time_machine.ranking.entertainment_features import entertainment_measurements
from nba_time_machine.ranking.morning_pipeline import MorningRankingPipeline
from nba_time_machine.ranking.queries import _score_from_row
from nba_time_machine.ranking.scoring import POSTGAME_VERSION
from nba_time_machine.sports.morning_models import EASTERN, Evidence, assess
from nba_time_machine.sports.morning_store import source_policy
from nba_time_machine.workbench.calculations import MISSING, TuningConfig, preview, candidate_preview
from nba_time_machine.workbench.enrichment import PlayerSettings, PatternSettings, enrichment_preview
from nba_time_machine.workbench.evidence import supporting_plays


async def slate_observations(session, day: date, as_of: datetime):
    start = datetime.combine(day, time.min, EASTERN).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time.min, EASTERN).astimezone(timezone.utc)
    o = GameObservationRecord
    latest = select(o.id.label("id"), func.row_number().over(
        partition_by=o.game_id, order_by=(o.observed_at.desc(), o.available_at.desc(), o.id.desc()),
    ).label("position")).where(o.observed_at <= as_of, o.available_at <= as_of).subquery()
    rows = (await session.scalars(select(o).join(latest, latest.c.id == o.id)
        .join(GameRecord, GameRecord.id == o.game_id)
        .join(SeasonRecord, SeasonRecord.id == GameRecord.season_id)
        .where(latest.c.position == 1, SeasonRecord.league == "NBA",
               o.scheduled_tip_at >= start, o.scheduled_tip_at < end)
        .order_by(o.scheduled_tip_at, o.game_id).limit(33))).all()
    if len(rows) > 32:
        raise ValueError("stored slate exceeds 32-game inspection limit")
    return rows


async def inspect_game(session, observation, as_of: datetime, baseline: TuningConfig, experiment: TuningConfig):
    game_id = observation.game_id
    game = await session.get(GameRecord, game_id)
    home = await session.get(TeamRecord, game.home_team_id)
    away = await session.get(TeamRecord, game.away_team_id)
    result = {"game_id": str(game_id), "home": home.name, "away": away.name,
        "tip": observation.scheduled_tip_at.isoformat(), "status": observation.status,
        "baseline": None, "experiment": None, "archived": None,
        "diagnostics": [], "evidence": None, "supporting_plays": [], "metrics": None}
    derived = await MorningRankingPipeline(session).derive(game_id, as_of=as_of)
    # Show why withheld, including retained evidence that failed ranking validation.
    facts = (await session.scalars(select(TemporalFactRecord).where(
        TemporalFactRecord.game_id == game_id,
        TemporalFactRecord.fact_type == "provider_game_evidence",
        TemporalFactRecord.source_id == observation.source_id,
        TemporalFactRecord.observed_at <= as_of, TemporalFactRecord.available_at <= as_of,
    ).order_by(TemporalFactRecord.observed_at.desc(), TemporalFactRecord.available_at.desc())
      .limit(2))).all()
    fact = derived[0] if derived else (facts[0] if facts else None)
    parsed = None
    if fact:
        source = await session.get(SourceRecord, fact.source_id)
        result["provenance"] = {"fact_id": str(fact.id), "source_id": fact.source_id,
            "source_verification": source.verification_status if source else "missing",
            "observed_at": fact.observed_at.isoformat(), "available_at": fact.available_at.isoformat(),
            "derivation_version": FEATURE_VERSION,
            "finality_basis": "validated final state observed; actual finish timestamp unknown"}
        try:
            parsed = assess(Evidence.model_validate({**fact.value, "observed_at": fact.observed_at}))
            result["evidence"] = parsed.model_dump(mode="json")
            result["provenance"]["source_url"] = (
                "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=" + quote(parsed.external_id, safe="")
                if parsed.provider == "espn" else
                "https://www.cbssports.com/nba/gametracker/playbyplay/" + quote(parsed.ref.cbs_abbr, safe="") + "/")
            result["diagnostics"].extend(parsed.pbp_errors)
            result["box_diagnostics"] = list(parsed.box_errors)
            if not derived:
                if observation.status != "final":
                    result["diagnostics"].append("game_not_final")
                if len(facts) > 1 and (facts[0].observed_at, facts[0].available_at) == (facts[1].observed_at, facts[1].available_at):
                    result["diagnostics"].append("ambiguous_same_time_evidence")
                if fact.valid_from > as_of or (fact.valid_to is not None and fact.valid_to <= as_of):
                    result["diagnostics"].append("evidence_not_valid_at_cutoff")
                if (fact.observed_at, fact.available_at) != (observation.observed_at, observation.available_at):
                    result["diagnostics"].append("evidence_observation_revision_mismatch")
                if parsed.ref.scheduled_at is None or parsed.ref.scheduled_at != observation.scheduled_tip_at:
                    result["diagnostics"].append("missing_or_inconsistent_scheduled_tip")
                if (parsed.home.score, parsed.away.score) != (observation.home_score, observation.away_score):
                    result["diagnostics"].append("evidence_observation_scores_mismatch")
                mapped = await session.scalar(select(SportsExternalIdentityRecord.game_id).where(
                    SportsExternalIdentityRecord.provider_key == parsed.provider,
                    SportsExternalIdentityRecord.entity_type == "game",
                    SportsExternalIdentityRecord.external_id == parsed.external_id))
                if mapped != game_id:
                    result["diagnostics"].append("canonical_game_mapping_mismatch")
                try:
                    source_policy(source, parsed.provider, manual=True)
                except ValueError:
                    result["diagnostics"].append("source_policy_not_approved")
        except (ValidationError, ValueError, TypeError):
            result["diagnostics"].append("invalid_evidence_schema")
    else:
        result["diagnostics"].append("no_stored_provider_game_evidence_at_this_as_of")
    if derived:
        fact, metrics, score = derived
        result["metrics"] = asdict(metrics)
        result["baseline"] = preview(metrics, baseline)
        measurements = entertainment_measurements(parsed)
        result["experiment"] = candidate_preview(metrics, measurements, experiment)
        if parsed:
            result["supporting_plays"] = supporting_plays(parsed, metrics)
    else:
        result["diagnostics"].append("ranking_withheld: latest final state, source policy, identity, timestamps or complete trajectory not established")
    if parsed:
        # Independent family diagnostics remain inspectable even when a complete
        # candidate is withheld (e.g. valid boxes but a corrected PBP trace).
        measurements = entertainment_measurements(parsed)
        candidate_details = result["experiment"].pop("enrichment", None) if result["experiment"] else None
        result["enrichment"] = candidate_details or enrichment_preview(
            measurements, experiment.player or PlayerSettings(), experiment.pattern or PatternSettings())
        result["enrichment"]["candidate_eligible"] = derived is not None and experiment.schema_version == 2
    row = await session.scalar(select(RecommendationScoreRecord).where(
        RecommendationScoreRecord.game_id == game_id,
        RecommendationScoreRecord.score_kind == "postgame",
        RecommendationScoreRecord.model_version == POSTGAME_VERSION,
        RecommendationScoreRecord.as_of <= as_of,
    ).order_by(RecommendationScoreRecord.as_of.desc(), RecommendationScoreRecord.id.desc()).limit(1))
    if row:
        archived = _score_from_row(row)
        eligible = archived is not None and derived is not None and archived.components == derived[2].components
        result["archived"] = {"as_of": row.as_of.isoformat(), "model_version": row.model_version,
            "score": archived.value if archived else None, "eligible": eligible,
            "status": "Matches current evidence" if eligible else "Withheld / different evidence or invalid archive"}
    return result


async def inspect_slate(session, day: date, as_of: datetime, baseline: TuningConfig, experiment: TuningConfig,
                        default_candidate: TuningConfig | None = None):
    games = []
    for observation in await slate_observations(session, day, as_of):
        games.append(await inspect_game(session, observation, as_of, baseline, experiment))
    return {"schema_version": 1, "slate_date": day.isoformat(), "as_of": as_of.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "coverage": "Stored observations only; missing games are not proof of an empty slate. No live fetch.",
        "baseline_config": baseline.model_dump(exclude_none=True), "experiment_config": experiment.model_dump(exclude_none=True),
        "default_candidate_config": (default_candidate or experiment).model_dump(exclude_none=True),
        "missing_criteria": MISSING, "games": games}
