from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from starter.agent import Agent
from tests.fixtures import sample_products, write_catalog


PROFILE = {
    "purchase_frequency": "monthly",
    "average_prior_rating": 4.2,
    "rating_style": "selective",
    "preference_tags": ["durable"],
    "summary": "Prefers durable products.",
}


def integration_products() -> list[dict[str, object]]:
    products = sample_products()
    for number in range(1, 7):
        products[number - 1] = {
            "parent_asin": f"MATCH-{number}",
            "title": f"Black leather boot {number}",
            "features": ["durable traction"],
            "details": {"material": "leather", "color": "black"},
            "description": ["Everyday boot"],
            "categories": ["Clothing", "Boots"],
            "store": "Example",
            "average_rating": 4.8,
            "rating_number": 100 + number,
            "price": 70.0 + number,
        }
    return products


def rotation_products() -> list[dict[str, object]]:
    return [
        {
            "parent_asin": f"RED-{number:02d}",
            "title": f"Red walking shoe {number}",
            "features": ["comfortable"],
            "details": {"material": "synthetic", "color": "red"},
            "description": ["Everyday footwear"],
            "categories": ["Clothing", "Shoes"],
            "store": "Example",
            "average_rating": 4.5,
            "rating_number": 100 - number,
            "price": 50.0 + number,
        }
        for number in range(1, 25)
    ]


class AgentIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.catalog_path = write_catalog(
            Path(self.temporary_directory.name),
            integration_products(),
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_agent_recommends_while_accumulating_constraint_answers(self) -> None:
        agent = Agent(catalog_path=self.catalog_path)
        self.addCleanup(agent.close)
        agent.reset("s1", PROFILE)

        first = agent.respond("s1", "I need boots", 1, 10)
        second = agent.respond("s1", "black leather", 2, 10)

        self.assertEqual(len(first["recommendations"]), 10)
        self.assertEqual(len(second["recommendations"]), 10)
        self.assertTrue(
            all(
                item["parent_asin"].startswith("MATCH-")
                for item in second["recommendations"][:5]
            )
        )
        self.assertEqual(
            len({item["parent_asin"] for item in second["recommendations"]}),
            10,
        )

    def test_empty_message_still_fills_the_requested_slate(self) -> None:
        agent = Agent(catalog_path=self.catalog_path)
        self.addCleanup(agent.close)
        agent.reset("s1", PROFILE)

        response = agent.respond("s1", "", 1, 10)

        self.assertEqual(len(response["recommendations"]), 10)

    def test_respond_requires_a_reset_session(self) -> None:
        agent = Agent(catalog_path=self.catalog_path)
        self.addCleanup(agent.close)

        with self.assertRaisesRegex(RuntimeError, "reset"):
            agent.respond("missing", "boots", 1, 10)

    def test_close_releases_agent_catalog_resources(self) -> None:
        agent = Agent(catalog_path=self.catalog_path)
        self.addCleanup(agent.close)
        agent.reset("s1", PROFILE)

        agent.close()

        with self.assertRaisesRegex(RuntimeError, "closed"):
            agent.respond("s1", "boots", 1, 10)

    def test_failed_slate_rotates_but_override_resets_suppression(self) -> None:
        catalog_path = write_catalog(
            Path(self.temporary_directory.name),
            rotation_products(),
        )
        agent = Agent(catalog_path=catalog_path)
        self.addCleanup(agent.close)
        agent.reset("rotate", PROFILE)

        first = agent.respond("rotate", "red shoes", 1, 10)
        second = agent.respond("rotate", "show me others", 2, 10)
        override = agent.respond("rotate", "Actually I need red shoes", 3, 10)
        first_ids = {item["parent_asin"] for item in first["recommendations"]}
        second_ids = {item["parent_asin"] for item in second["recommendations"]}
        override_ids = {item["parent_asin"] for item in override["recommendations"]}

        self.assertFalse(first_ids & second_ids)
        self.assertTrue(first_ids & override_ids)

    def test_agent_recommends_ten_products_while_asking(self) -> None:
        agent = Agent(catalog_path=self.catalog_path)
        self.addCleanup(agent.close)
        agent.reset("ask", PROFILE)

        response = agent.respond("ask", "I need boots", 1, 10)

        self.assertEqual(len(response["recommendations"]), 10)
        self.assertIn(
            response["ask_attribute"],
            {"material", "color", "size", "style", "brand", "feature"},
        )
        self.assertIn("?", response["message"])

    def test_declined_question_is_not_repeated(self) -> None:
        agent = Agent(catalog_path=self.catalog_path)
        self.addCleanup(agent.close)
        agent.reset("decline", PROFILE)
        first = agent.respond("decline", "I need boots", 1, 10)

        second = agent.respond("decline", "no preference", 2, 10)

        self.assertIsNotNone(first["ask_attribute"])
        self.assertNotEqual(second["ask_attribute"], first["ask_attribute"])


if __name__ == "__main__":
    unittest.main()
