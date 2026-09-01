from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from experiments.demo_session import render_demo_session, run_demo_session


class _ScriptedAgent:
    def __init__(self, target: str) -> None:
        self.target = target
        self.messages: list[str] = []

    def reset(self, session_id: str, user_profile: dict[str, object]) -> None:
        self.session_id = session_id
        self.user_profile = user_profile

    def respond(
        self,
        session_id: str,
        user_message: str,
        turn: int,
        top_k: int,
    ) -> dict[str, object]:
        self.messages.append(user_message)
        return {
            "message": "Here are the current matches. What material do you prefer?",
            "ask_attribute": "material",
            "recommendations": [{"parent_asin": self.target}],
        }


class DemoSessionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.catalog_path = root / "catalog.jsonl"
        self.dataset_path = root / "public_set.jsonl"
        products = [
            {
                "parent_asin": "TARGET",
                "title": "Wool fedora",
                "features": ["wool", "buckle closure"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Hats"],
                "store": "Example",
            },
            {
                "parent_asin": "OTHER",
                "title": "Canvas cap",
                "features": ["canvas"],
                "details": {},
                "description": [],
                "categories": ["Clothing", "Hats"],
                "store": "Example",
            },
        ]
        sample = {
            "sample_id": "public_demo",
            "scenario_type": "intent_override",
            "user_profile": {"summary": "prefers comfortable hats"},
            "ground_truth": {"parent_asin": "TARGET"},
            "intent_card": {
                "target_category": "Wool fedora",
                "hard_constraints": ["wool"],
                "soft_preferences": ["buckle closure"],
            },
            "behavior": {
                "scenario_type": "intent_override",
                "override": {
                    "turn": 3,
                    "old_value": "buckle closure",
                    "new_value": "wool",
                    "message": "Actually, ignore that. What I need is wool.",
                },
            },
        }
        self.catalog_path.write_text(
            "".join(json.dumps(product) + "\n" for product in products),
            encoding="utf-8",
        )
        self.dataset_path.write_text(json.dumps(sample) + "\n", encoding="utf-8")

    def test_override_target_is_counted_only_after_the_new_intent_is_active(
        self,
    ) -> None:
        agent = _ScriptedAgent("TARGET")

        transcript = run_demo_session(
            "public_demo",
            self.catalog_path,
            self.dataset_path,
            agent=agent,
        )

        turns = transcript["turns"]
        self.assertEqual(len(turns), 3)
        self.assertEqual(turns[0]["target_rank"], 1)
        self.assertFalse(turns[0]["eligible_hit"])
        self.assertFalse(turns[1]["eligible_hit"])
        self.assertTrue(turns[2]["eligible_hit"])
        self.assertEqual(
            transcript["result"],
            {"hit": True, "first_hit_turn": 3, "best_rank": 1},
        )
        self.assertEqual(
            agent.messages[2],
            "Actually, ignore that. What I need is wool.",
        )

    def test_unknown_sample_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "unknown sample_id"):
            run_demo_session(
                "missing",
                self.catalog_path,
                self.dataset_path,
                agent=_ScriptedAgent("TARGET"),
            )

    def test_text_render_names_the_scenario_turns_and_result(self) -> None:
        transcript = run_demo_session(
            "public_demo",
            self.catalog_path,
            self.dataset_path,
            agent=_ScriptedAgent("TARGET"),
        )

        rendered = render_demo_session(transcript)

        self.assertIn("DEMO public_demo | intent_override", rendered)
        self.assertIn("TURN 3", rendered)
        self.assertIn("Target intent: not active yet", rendered)
        self.assertIn("RESULT: HIT on turn 3 at rank 1", rendered)


if __name__ == "__main__":
    unittest.main()
