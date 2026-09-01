from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Protocol

from evaluator.local_evaluator import (
    MAX_TURNS,
    TOP_K,
    catalog_index,
    coarse_category,
    customer_reply,
    initial_message,
    load_jsonl,
    materialize_hidden_fields,
    normalize_recommendations,
)
from starter.agent import Agent


class DemoAgent(Protocol):
    def reset(self, session_id: str, user_profile: dict[str, object]) -> None: ...

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict[str, object]: ...


def run_demo_session(
    sample_id: str,
    catalog_path: str | Path = "data/catalog.jsonl",
    dataset_path: str | Path = "data/public_set.jsonl",
    artifact_path: str | Path | None = None,
    agent: DemoAgent | None = None,
) -> dict[str, object]:
    """Run one public session with the organizer's deterministic turn policy.

    Ground truth is used only by this presentation harness to label the result.
    The Agent receives exactly the same profile and messages as it does during
    evaluation.
    """
    samples = load_jsonl(dataset_path)
    matches = [sample for sample in samples if sample.get("sample_id") == sample_id]
    if not matches:
        raise ValueError(f"unknown sample_id: {sample_id}")
    sample = matches[0]

    catalog_ids, categories, products = catalog_index(catalog_path)
    target = str(sample["ground_truth"]["parent_asin"])
    intent_card, behavior = materialize_hidden_fields(sample, products)
    effective_sample = {
        **sample,
        "intent_card": intent_card,
        "behavior": behavior,
    }

    active_agent: DemoAgent
    owns_agent = agent is None
    if agent is None:
        active_agent = Agent(catalog_path, artifact_path=artifact_path)
    else:
        active_agent = agent

    session_id = f"demo_{sample_id}"
    disclosed: set[str] = set()
    boundary_used = False
    override_applied = sample["scenario_type"] != "intent_override"
    user_message = initial_message(
        effective_sample,
        coarse_category(categories.get(target, [])),
        disclosed,
    )
    turns: list[dict[str, object]] = []
    hit_turn: int | None = None
    best_rank: int | None = None

    try:
        active_agent.reset(session_id, sample["user_profile"])
        for turn in range(1, MAX_TURNS + 1):
            response = active_agent.respond(
                session_id,
                user_message,
                turn,
                TOP_K,
            )
            if not isinstance(response, dict) or not isinstance(
                response.get("message"), str
            ):
                raise RuntimeError(f"Agent returned an invalid response on turn {turn}")

            ranked = normalize_recommendations(
                response.get("recommendations"),
                catalog_ids,
            )
            visible_rank = ranked.index(target) + 1 if target in ranked else None
            eligible_hit = override_applied and visible_rank is not None
            turns.append({
                "turn": turn,
                "customer_message": user_message,
                "agent_message": response["message"],
                "ask_attribute": response.get("ask_attribute"),
                "target_intent_active": override_applied,
                "target_rank": visible_rank,
                "eligible_hit": eligible_hit,
                "recommendations": [
                    {
                        "rank": rank,
                        "parent_asin": parent_asin,
                        "title": str(products[parent_asin].get("title") or ""),
                    }
                    for rank, parent_asin in enumerate(ranked, start=1)
                ],
            })
            if eligible_hit:
                hit_turn = turn
                best_rank = visible_rank
                break
            if turn == MAX_TURNS:
                break

            override = behavior.get("override") or {}
            if not override_applied and turn + 1 == int(override.get("turn", 3)):
                override_applied = True
                new_value = str(override.get("new_value", ""))
                if new_value:
                    disclosed.add(new_value)
                user_message = str(
                    override.get(
                        "message",
                        "Actually, please ignore my earlier preference.",
                    )
                )
            else:
                user_message, boundary_used = customer_reply(
                    effective_sample,
                    response.get("ask_attribute"),
                    disclosed,
                    boundary_used,
                )

        history_method = getattr(active_agent, "turn_history", None)
        raw_history = history_method(session_id) if callable(history_method) else ()
        history = [
            asdict(record) if is_dataclass(record) else record
            for record in raw_history
        ]
    finally:
        if owns_agent:
            close_method = getattr(active_agent, "close", None)
            if callable(close_method):
                close_method()

    return {
        "sample_id": sample_id,
        "scenario_type": sample["scenario_type"],
        "target": {
            "parent_asin": target,
            "title": str(products[target].get("title") or ""),
        },
        "user_profile": sample["user_profile"],
        "intent_card": intent_card,
        "behavior": behavior,
        "turns": turns,
        "turn_history": history,
        "result": {
            "hit": hit_turn is not None,
            "first_hit_turn": hit_turn,
            "best_rank": best_rank,
        },
    }


def render_demo_session(transcript: dict[str, object]) -> str:
    target = transcript["target"]
    result = transcript["result"]
    assert isinstance(target, dict)
    assert isinstance(result, dict)
    lines = [
        f"DEMO {transcript['sample_id']} | {transcript['scenario_type']}",
        f"Target: {target['parent_asin']} - {target['title']}",
        "",
    ]
    turns = transcript["turns"]
    assert isinstance(turns, list)
    for item in turns:
        assert isinstance(item, dict)
        lines.extend((
            f"TURN {item['turn']}",
            f"Customer: {item['customer_message']}",
            f"Agent: {item['agent_message']}",
            f"Asked attribute: {item['ask_attribute'] or 'none'}",
        ))
        recommendations = item["recommendations"]
        assert isinstance(recommendations, list)
        for recommendation in recommendations[:3]:
            assert isinstance(recommendation, dict)
            lines.append(
                f"  {recommendation['rank']}. {recommendation['parent_asin']}"
                f" - {recommendation['title']}"
            )
        intent_status = "active" if item["target_intent_active"] else "not active yet"
        rank = item["target_rank"] if item["target_rank"] is not None else "not in Top 10"
        lines.extend((
            f"Target intent: {intent_status}; target rank: {rank}",
            "",
        ))
    outcome = (
        f"HIT on turn {result['first_hit_turn']} at rank {result['best_rank']}"
        if result["hit"]
        else "MISS after 10 turns"
    )
    lines.append(f"RESULT: {outcome}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render one public multi-turn session for the demo video"
    )
    parser.add_argument("--sample-id", default="public_0003")
    parser.add_argument("--catalog", default="data/catalog.jsonl")
    parser.add_argument("--dataset", default="data/public_set.jsonl")
    parser.add_argument("--artifact")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args()

    transcript = run_demo_session(
        sample_id=args.sample_id,
        catalog_path=args.catalog,
        dataset_path=args.dataset,
        artifact_path=args.artifact,
    )
    if args.as_json:
        print(json.dumps(transcript, indent=2))
    else:
        print(render_demo_session(transcript))


if __name__ == "__main__":
    main()
