from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from frisbee_5v5.report import build_accessible_report, write_accessible_report


class ReportTests(unittest.TestCase):
    def sample_events(self) -> list[dict[str, object]]:
        return [
            {
                "type": "episode_start",
                "seed": 7,
                "model": "deepseek-v4-pro",
                "thinking": "enabled",
                "state": {"players": {"blue_1": {}, "red_1": {}}, "possession_team": "blue"},
            },
            {
                "type": "frame",
                "frame_start": 0,
                "frame_end": 1,
                "wall_seconds": 2.5,
                "estimated_cost_usd": 0.01,
                "cumulative_estimated_cost_usd": 0.01,
                "usage": {"total_tokens": 100, "prompt_tokens": 70, "completion_tokens": 30},
                "events": [{"type": "movement", "player": "blue_1", "to": {"x": 1, "y": 2}}],
                "model_results": [
                    {
                        "player_id": "blue_1",
                        "ok": True,
                        "latency_seconds": 2.4,
                        "finish_reason": "stop",
                        "action": {"action": "hold", "reason": "waiting"},
                        "usage": {"total_tokens": 100, "prompt_tokens": 70, "completion_tokens": 30},
                        "raw_content": '{"action":"hold","reason":"waiting"}',
                        "reasoning_content": "thinking trace",
                    }
                ],
            },
            {"type": "episode_end", "frames": 1, "api_calls": 10, "estimated_cost_usd": 0.01, "stop_reason": "max_frames"},
        ]

    def test_build_accessible_report_includes_agent_feedback(self) -> None:
        report = build_accessible_report(self.sample_events(), "sample.jsonl")
        self.assertIn("sample.jsonl Agent Report", report)
        self.assertIn("blue_1", report)
        self.assertIn("waiting", report)
        self.assertIn("Raw model content", report)
        self.assertIn("Returned thinking trace", report)
        self.assertIn("Full frame JSON", report)

    def test_write_accessible_report_writes_html_next_to_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log_path = Path(tmp) / "run.jsonl"
            log_path.write_text("\n".join(json.dumps(event) for event in self.sample_events()), encoding="utf-8")
            report_path = write_accessible_report(log_path)
            self.assertEqual(report_path.name, "run_report.html")
            self.assertIn("<!doctype html>", report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
