from __future__ import annotations

import asyncio
import json
import math
import os
import random
import statistics
import time
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Iterable
from modules import complicated_transform, expensive_simulation, load_users, run_healthcheck, save_report

APP_NAME = "MegaTestApp"
DEBUG = True
DEFAULT_TIMEOUT = 2.5
DATA_DIR = Path("data")
CACHE: dict[str, Any] = {}

@dataclass
class User:
    id: int
    name: str
    scores: list[int]

def log_call(func: Callable) -> Callable:
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        print(f"[LOG] calling {func.__name__}")
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        print(f"[LOG] finished {func.__name__} in {elapsed:.4f}s")
        return result
    return wrapper

def require_positive_numbers(values: Iterable[float]) -> None:
    if any(v < 0 for v in values):
        raise ValueError("negative values are not allowed")

def normalize_name(name: str) -> str:
    return " ".join(part.capitalize() for part in name.strip().split())

def _internal_score_multiplier() -> float:
    return 1.15 if DEBUG else 1.0

@log_call

@log_call
def compute_user_stats(users: list[User]) -> dict[str, dict[str, float]]:
    results: dict[str, dict[str, float]] = {}

    for user in users:
        if not user.scores:
            results[user.name] = {
                "mean": 0.0,
                "median": 0.0,
                "stdev": 0.0,
                "weighted": 0.0,
            }
            continue

        require_positive_numbers(user.scores)

        mean_val = statistics.mean(user.scores)
        median_val = statistics.median(user.scores)
        stdev_val = statistics.pstdev(user.scores)
        weighted = mean_val * _internal_score_multiplier()

        results[user.name] = {
            "mean": round(mean_val, 2),
            "median": round(median_val, 2),
            "stdev": round(stdev_val, 2),
            "weighted": round(weighted, 2),
        }

    CACHE["stats"] = results
    return results

async def fetch_remote_config() -> dict[str, Any]:
    await asyncio.sleep(0.1)
    return {
        "retry_limit": 3,
        "feature_flags": {
            "beta_dashboard": True,
            "smart_cache": False,
        },
        "timeout": DEFAULT_TIMEOUT,
    }

@log_call

def uses_env_and_globals() -> str:
    mode = os.getenv("APP_MODE", "development")
    CACHE["last_mode"] = mode
    return f"{APP_NAME}:{mode}:{DEBUG}"

def orchestrate(path: str, out_path: str) -> dict[str, Any]:
    users = load_users(path)
    stats = compute_user_stats(users)
    report_path = save_report(stats, out_path)

    transformed = complicated_transform(
        [score for user in users for score in user.scores if score > 0]
    )
    sim = expensive_simulation(seed=42, n=1000)
    env_info = uses_env_and_globals()

    return {
        "report_path": report_path,
        "user_count": len(users),
        "transform_summary": transformed,
        "simulation": sim,
        "env": env_info,
    }

async def main() -> None:
    DATA_DIR.mkdir(exist_ok=True)

    sample_path = DATA_DIR / "users.json"
    sample_data = [
        {"id": 1, "name": "alice smith", "scores": [10, 20, 30, 40]},
        {"id": 2, "name": "bob jones", "scores": [15, 25, 35]},
        {"id": 3, "name": "charlie", "scores": [5, 5, 5, 5]},
    ]
    sample_path.write_text(json.dumps(sample_data, indent=2), encoding="utf-8")

    result = orchestrate(str(sample_path), str(DATA_DIR / "report.json"))
    print(json.dumps(result, indent=2))

    healthy, cfg = await run_healthcheck()
    print("healthcheck:", healthy)
    print("config:", json.dumps(cfg, indent=2))

if __name__ == "__main__":
    asyncio.run(main())