from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEEPSEEK_PRICES_PER_MILLION = {
    "deepseek-v4-flash": {
        "cache_hit_input": 0.0028,
        "cache_miss_input": 0.14,
        "output": 0.28,
    },
    "deepseek-v4-pro": {
        "cache_hit_input": 0.003625,
        "cache_miss_input": 0.435,
        "output": 0.87,
    },
}


@dataclass(frozen=True)
class ProbeConfig:
    api_key: str
    calls: int = 10
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    timeout: float = 45.0
    max_tokens: int = 80
    warmup: bool = False
    user_id: str | None = None

    @property
    def endpoint(self) -> str:
        return self.base_url.rstrip("/") + "/chat/completions"


@dataclass
class ProbeResult:
    call_id: int
    ok: bool
    latency_seconds: float
    status: int | None = None
    action: str | None = None
    content: str | None = None
    error: str | None = None
    usage: dict[str, Any] | None = None
    parsed_json: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "ok": self.ok,
            "latency_seconds": round(self.latency_seconds, 3),
            "status": self.status,
            "action": self.action,
            "error": self.error,
            "usage": self.usage or {},
            "parsed_json": self.parsed_json or {},
        }


def discover_env_files(start: Path | None = None) -> list[Path]:
    current = (start or Path.cwd()).resolve()
    candidates: list[Path] = []
    for directory in [current, *current.parents]:
        candidate = directory / ".env"
        if candidate.exists():
            candidates.append(candidate)
    return candidates


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def get_api_key(env_file: Path | None = None, env_var: str = "DEEPSEEK_API_KEY") -> str | None:
    env_value = normalize_api_key(os.environ.get(env_var))
    if env_value:
        return env_value
    files = [env_file] if env_file else discover_env_files()
    for file_path in files:
        if not file_path or not file_path.exists():
            continue
        value = normalize_api_key(load_env_file(file_path).get(env_var))
        if value:
            return value
    return None


def normalize_api_key(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    if stripped.lower() in {"your_token_here", "your_deepseek_api_key_here", "replace_me"}:
        return None
    return stripped


def build_messages(call_id: int) -> list[dict[str, str]]:
    system_prompt = """
You are controlling one player in a future 5v5 ultimate-style frisbee simulation.
This is only an API concurrency probe, not the final game.
Return a compact json object with exactly these keys:
{
  "action": "move" | "hold" | "scan",
  "dx": integer from -1 to 1,
  "dy": integer from -1 to 1,
  "reason": short string
}
Do not include markdown. Do not include extra keys.
""".strip()
    observation = {
        "frame": 0,
        "player_id": f"probe_player_{call_id}",
        "team": "blue" if call_id < 5 else "red",
        "position": {"x": call_id % 5, "y": call_id // 5},
        "disc": {"x": 5, "y": 4, "state": "loose"},
        "nearby_space": [
            {"x": 1, "y": 0, "clear": True},
            {"x": 0, "y": 1, "clear": True},
            {"x": -1, "y": 0, "clear": call_id % 2 == 0},
        ],
        "instruction": "Choose one safe json action for this player.",
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "Current observation json:\n" + json.dumps(observation, sort_keys=True)},
    ]


def build_payload(config: ProbeConfig, call_id: int) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": config.model,
        "messages": build_messages(call_id),
        "stream": False,
        "max_tokens": config.max_tokens,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},
    }
    if config.user_id:
        payload["user_id"] = config.user_id
    return payload


def call_deepseek(config: ProbeConfig, call_id: int) -> ProbeResult:
    payload = build_payload(config, call_id)
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        config.endpoint,
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=config.timeout) as response:
            raw = response.read().decode("utf-8")
            latency = time.monotonic() - started
            data = json.loads(raw)
            content = data["choices"][0]["message"].get("content") or ""
            parsed = parse_action_json(content)
            return ProbeResult(
                call_id=call_id,
                ok=parsed is not None,
                latency_seconds=latency,
                status=response.status,
                action=parsed.get("action") if parsed else None,
                content=content,
                error=None if parsed else "Response content was not parseable JSON.",
                usage=data.get("usage"),
                parsed_json=parsed,
            )
    except urllib.error.HTTPError as error:
        latency = time.monotonic() - started
        detail = error.read().decode("utf-8", errors="replace")[:1000]
        return ProbeResult(call_id, False, latency, error.code, error=f"HTTP {error.code}: {detail}")
    except Exception as error:  # noqa: BLE001 - CLI probe should report any network/parser failure.
        latency = time.monotonic() - started
        return ProbeResult(call_id, False, latency, error=repr(error))


def parse_action_json(content: str) -> dict[str, Any] | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    action = parsed.get("action")
    if action not in {"move", "hold", "scan"}:
        return None
    for key in ("dx", "dy"):
        value = parsed.get(key)
        if not isinstance(value, int) or value < -1 or value > 1:
            return None
    if not isinstance(parsed.get("reason"), str):
        return None
    return parsed


async def run_probe(config: ProbeConfig) -> dict[str, Any]:
    warmup_result = None
    if config.warmup:
        warmup_result = await asyncio.to_thread(call_deepseek, config, -1)

    started = time.monotonic()
    tasks = [asyncio.to_thread(call_deepseek, config, call_id) for call_id in range(config.calls)]
    results = await asyncio.gather(*tasks)
    wall_seconds = time.monotonic() - started
    return summarize_results(config, results, wall_seconds, warmup_result)


def summarize_results(
    config: ProbeConfig,
    results: list[ProbeResult],
    wall_seconds: float,
    warmup_result: ProbeResult | None = None,
) -> dict[str, Any]:
    latencies = [result.latency_seconds for result in results]
    usage_totals = total_usage(results)
    return {
        "model": config.model,
        "calls_requested": config.calls,
        "calls_ok": sum(1 for result in results if result.ok),
        "calls_failed": sum(1 for result in results if not result.ok),
        "wall_seconds": round(wall_seconds, 3),
        "latency_seconds": {
            "min": round(min(latencies), 3) if latencies else 0,
            "median": round(statistics.median(latencies), 3) if latencies else 0,
            "max": round(max(latencies), 3) if latencies else 0,
        },
        "usage_totals": usage_totals,
        "estimated_cost_usd": estimate_cost_usd(config.model, usage_totals),
        "warmup": warmup_result.as_dict() if warmup_result else None,
        "results": [result.as_dict() for result in results],
    }


def total_usage(results: list[ProbeResult]) -> dict[str, int]:
    keys = [
        "prompt_tokens",
        "completion_tokens",
        "total_tokens",
        "prompt_cache_hit_tokens",
        "prompt_cache_miss_tokens",
    ]
    totals = {key: 0 for key in keys}
    for result in results:
        usage = result.usage or {}
        for key in keys:
            value = usage.get(key, 0)
            if isinstance(value, int):
                totals[key] += value
    return totals


def estimate_cost_usd(model: str, usage: dict[str, int]) -> float | None:
    prices = DEEPSEEK_PRICES_PER_MILLION.get(model)
    if not prices:
        return None
    cache_hit = usage.get("prompt_cache_hit_tokens", 0)
    cache_miss = usage.get("prompt_cache_miss_tokens", usage.get("prompt_tokens", 0))
    output = usage.get("completion_tokens", 0)
    cost = (
        cache_hit * prices["cache_hit_input"]
        + cache_miss * prices["cache_miss_input"]
        + output * prices["output"]
    ) / 1_000_000
    return round(cost, 8)


def dry_run_summary(config: ProbeConfig) -> dict[str, Any]:
    payload = build_payload(config, 0)
    return {
        "dry_run": True,
        "endpoint": config.endpoint,
        "model": config.model,
        "calls": config.calls,
        "has_api_key": bool(config.api_key),
        "first_payload_without_secret": payload,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test concurrent DeepSeek calls for the frisbee agent system.")
    parser.add_argument("--calls", type=int, default=10, help="Number of concurrent calls to send.")
    parser.add_argument("--model", default="deepseek-v4-flash", help="DeepSeek model name.")
    parser.add_argument("--base-url", default="https://api.deepseek.com", help="DeepSeek API base URL.")
    parser.add_argument("--timeout", type=float, default=45.0, help="Per-request timeout in seconds.")
    parser.add_argument("--max-tokens", type=int, default=80, help="Maximum output tokens per call.")
    parser.add_argument("--warmup", action="store_true", help="Send one authentication/cache warmup call before the batch.")
    parser.add_argument("--dry-run", action="store_true", help="Print the request payload without calling the API.")
    parser.add_argument("--env-file", type=Path, help="Optional .env path containing DEEPSEEK_API_KEY.")
    parser.add_argument("--api-key-env", default="DEEPSEEK_API_KEY", help="Environment variable containing the token.")
    parser.add_argument("--user-id", help="Optional DeepSeek user_id. Use one shared id for this probe.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = get_api_key(args.env_file, args.api_key_env)
    if not api_key and not args.dry_run:
        print(
            "No DeepSeek API key found. Set DEEPSEEK_API_KEY in your shell or create "
            ".env in this project folder from .env.example.",
        )
        return 2

    config = ProbeConfig(
        api_key=api_key or "",
        calls=args.calls,
        model=args.model,
        base_url=args.base_url,
        timeout=args.timeout,
        max_tokens=args.max_tokens,
        warmup=args.warmup,
        user_id=args.user_id,
    )
    if args.dry_run:
        print(json.dumps(dry_run_summary(config), indent=2))
        return 0

    summary = asyncio.run(run_probe(config))
    print(json.dumps(summary, indent=2))
    return 0 if summary["calls_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
