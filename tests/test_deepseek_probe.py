from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from frisbee_5v5.deepseek_probe import (
    ProbeConfig,
    build_payload,
    estimate_cost_usd,
    get_api_key,
    load_env_file,
    parse_action_json,
    total_usage,
)


class DeepSeekProbeTests(unittest.TestCase):
    def test_payload_uses_flash_and_json_mode(self) -> None:
        payload = build_payload(ProbeConfig(api_key="secret"), 3)
        self.assertEqual(payload["model"], "deepseek-v4-flash")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertIn("json", payload["messages"][0]["content"].lower())

    def test_parse_action_json_validates_shape(self) -> None:
        action = parse_action_json('{"action":"move","dx":1,"dy":0,"reason":"advance"}')
        self.assertEqual(action["action"], "move")
        self.assertIsNone(parse_action_json('{"action":"teleport","dx":9,"dy":0,"reason":"bad"}'))

    def test_load_env_file_reads_token_without_export_syntax(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("DEEPSEEK_API_KEY='abc123'\nOTHER=value\n")
            values = load_env_file(path)
        self.assertEqual(values["DEEPSEEK_API_KEY"], "abc123")

    def test_get_api_key_ignores_placeholder_value(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("DEEPSEEK_API_KEY=your_token_here\n")
            self.assertIsNone(get_api_key(path))

    def test_cost_estimate_uses_cache_hit_and_miss_tokens(self) -> None:
        usage = {
            "prompt_cache_hit_tokens": 1_000_000,
            "prompt_cache_miss_tokens": 1_000_000,
            "completion_tokens": 1_000_000,
        }
        self.assertEqual(estimate_cost_usd("deepseek-v4-flash", usage), 0.4228)

    def test_total_usage_sums_known_usage_keys(self) -> None:
        class Result:
            def __init__(self) -> None:
                self.usage = {"prompt_tokens": 5, "completion_tokens": 2}

        totals = total_usage([Result(), Result()])
        self.assertEqual(totals["prompt_tokens"], 10)
        self.assertEqual(totals["completion_tokens"], 4)


if __name__ == "__main__":
    unittest.main()
