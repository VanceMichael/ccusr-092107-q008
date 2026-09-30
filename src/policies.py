"""城市政策版本库：按受理时点取版，版本在受理时固定。"""

import json
from datetime import date
from pathlib import Path


class PolicyNotFound(Exception):
    """住房所在地或时点没有可用政策。"""


def load_policies(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _effective(version: dict, on: date) -> bool:
    start = date.fromisoformat(version["effective_from"])
    end_raw = version.get("effective_to")
    end = date.fromisoformat(end_raw) if end_raw else None
    return start <= on and (end is None or on < end)


def resolve_policy(policies: dict, city_code: str, at: str | date) -> dict:
    """返回受理时点对住房所在地生效的政策版本（完整版本对象）。"""
    on = at if isinstance(at, date) else date.fromisoformat(at)
    for city in policies["cities"]:
        if city["city_code"] != city_code:
            continue
        matched = [v for v in city["versions"] if _effective(v, on)]
        if not matched:
            raise PolicyNotFound(f"{city_code} 在 {on} 无生效政策")
        chosen = max(matched, key=lambda v: v["version"])
        return {
            "city_code": city_code,
            "city_name": city["city_name"],
            "mutual_recognition_from": city.get("mutual_recognition_from"),
            **chosen,
        }
    raise PolicyNotFound(f"城市 {city_code} 未配置政策")


def rule_for(policy: dict, scenario: str) -> dict:
    try:
        return policy["rules"][scenario]
    except KeyError as exc:
        raise PolicyNotFound(f"政策版本 {policy['version']} 不支持场景 {scenario}") from exc


def mutual_recognition_active(policy: dict, at: str | date) -> bool:
    raw = policy.get("mutual_recognition_from")
    if not raw:
        return False
    on = at if isinstance(at, date) else date.fromisoformat(at)
    return on >= date.fromisoformat(raw)
