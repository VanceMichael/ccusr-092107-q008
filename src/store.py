"""从样例资料文件加载政策版本库与账户。"""

import json
from datetime import date, datetime
from pathlib import Path

from .domain import Account, RestrictionRecord, Scenario, WithdrawalRecord
from .policy import PolicyBook, PolicyVersion, ScenarioRule


def load_policy_book(path: Path) -> PolicyBook:
    raw = json.loads(path.read_text(encoding="utf-8"))
    book = PolicyBook()
    for city_block in raw["cities"]:
        for v in city_block["versions"]:
            effective_to = v.get("effective_to")
            book.add(
                PolicyVersion(
                    city=city_block["city"],
                    version=v["version"],
                    effective_from=date.fromisoformat(v["effective_from"]),
                    effective_to=(
                        date.fromisoformat(effective_to) if effective_to else None
                    ),
                    scenarios={
                        name: ScenarioRule(
                            annual_limit=rule["annual_limit"],
                            requires_vouchers=rule["requires_vouchers"],
                            requires_family_auth=rule["requires_family_auth"],
                        )
                        for name, rule in v["scenarios"].items()
                    },
                    restriction_years=dict(v["restriction_years"]),
                )
            )
    return book


def load_accounts(path: Path) -> dict[str, Account]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    accounts: dict[str, Account] = {}
    for a in raw["accounts"]:
        accounts[a["account_id"]] = Account(
            account_id=a["account_id"],
            balance=a["balance"],
            frozen=a.get("frozen", 0),
            withdrawals=[
                WithdrawalRecord(
                    house_id=w["house_id"],
                    scenario=Scenario(w["scenario"]),
                    amount=w["amount"],
                    paid_at=datetime.fromisoformat(w["paid_at"]),
                )
                for w in a.get("withdrawals", [])
            ],
            restrictions=[
                RestrictionRecord(
                    kind=r["kind"],
                    recorded_at=datetime.fromisoformat(r["recorded_at"]),
                )
                for r in a.get("restrictions", [])
            ],
        )
    return accounts
