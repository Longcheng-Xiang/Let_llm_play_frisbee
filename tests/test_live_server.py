from __future__ import annotations

import unittest

from frisbee_5v5.live_server import (
    DEFAULT_GAME_VERSION,
    DEFAULT_MAX_FRAMES,
    DEFAULT_MODEL,
    DEFAULT_THINKING,
    NON_THINKING_MAX_TOKENS_DEFAULT,
    THINKING_MAX_TOKENS_DEFAULT,
    LiveRunController,
    default_max_tokens_for_thinking,
)


class LiveServerConfigTests(unittest.TestCase):
    def test_thinking_mode_gets_larger_output_budget(self) -> None:
        self.assertEqual(default_max_tokens_for_thinking("disabled"), NON_THINKING_MAX_TOKENS_DEFAULT)
        self.assertEqual(default_max_tokens_for_thinking("enabled"), THINKING_MAX_TOKENS_DEFAULT)
        self.assertEqual(THINKING_MAX_TOKENS_DEFAULT, 8000)
        self.assertGreater(THINKING_MAX_TOKENS_DEFAULT, NON_THINKING_MAX_TOKENS_DEFAULT)

    def test_idle_status_matches_live_viewer_defaults(self) -> None:
        status = LiveRunController().status()
        self.assertEqual(status["game_version"], DEFAULT_GAME_VERSION)
        self.assertEqual(status["model"], DEFAULT_MODEL)
        self.assertEqual(status["thinking"], DEFAULT_THINKING)
        self.assertEqual(status["max_frames"], DEFAULT_MAX_FRAMES)
        self.assertEqual(status["max_tokens"], THINKING_MAX_TOKENS_DEFAULT)


if __name__ == "__main__":
    unittest.main()
