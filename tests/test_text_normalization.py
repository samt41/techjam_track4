from __future__ import annotations

import unittest

from starter.shopping_agent.text_normalization import match_key


class MatchKeyTest(unittest.TestCase):
    def test_collapses_spacing_around_separators(self) -> None:
        # The catalog stores the same concept with inconsistent separator
        # spacing; the match key must make the variants equal.
        self.assertEqual(match_key("material: alloy"), match_key("material:alloy"))
        self.assertEqual(match_key("black, white"), match_key("black,white"))
        self.assertEqual(
            match_key("fabric / synthetic"),
            match_key("fabric/synthetic"),
        )

    def test_preserves_the_separator_character(self) -> None:
        # Only the surrounding whitespace is removed, so distinct concepts do
        # not collide into one token.
        self.assertEqual(match_key("black, white"), "black,white")
        self.assertNotEqual(match_key("black, white"), "blackwhite")

    def test_partial_substring_matches_still_hold(self) -> None:
        # A single value must still be found inside a normalized multi-value
        # string, so partial matching is not broken by the normalization.
        self.assertIn(match_key("white"), match_key("black, white"))
        self.assertIn(match_key("black"), match_key("black, white"))

    def test_leaves_unrelated_punctuation_untouched(self) -> None:
        self.assertEqual(match_key("north face"), "north face")
        self.assertEqual(match_key("100% cotton"), "100% cotton")


if __name__ == "__main__":
    unittest.main()
