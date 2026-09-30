"""账户台账：余额、冻结、缴存、家庭授权、凭证、历史占用与限制。"""

import json
from datetime import date
from pathlib import Path

from .timeutil import d

FRAUD_WITHDRAWAL_YEARS = 3
LOAN_FRAUD_YEARS = 5


def load_accounts(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class Ledger:
    """内存台账，持有样例数据并登记在途冻结与额度占用。"""

    def __init__(self, data: dict):
        self.accounts = {a["account_id"]: dict(a) for a in data["accounts"]}
        self.holds: dict[str, dict] = {}
        self.occupations: list[dict] = []

    def get(self, account_id: str) -> dict:
        return self.accounts[account_id]

    # ---- 余额与转移冻结 ----

    def held(self, account_id: str) -> int:
        return sum(h["amount"] for h in self.holds.values() if h["account_id"] == account_id)

    def available_balance(self, account_id: str) -> int:
        account = self.get(account_id)
        return account["balance"] - account["frozen"] - self.held(account_id)

    def transfer_frozen(self, account_id: str) -> bool:
        account = self.get(account_id)
        return account["status"] == "transfer_frozen" or account["frozen"] > 0

    def release_transfer(self, account_id: str, released_at: str) -> None:
        account = self.get(account_id)
        account["frozen"] = 0
        account["status"] = "normal"
        if account.get("transfer"):
            account["transfer"]["released_at"] = released_at

    # ---- 缴存月数（外地互信互认时合并） ----

    def eligible_months(self, account_id: str, mutual: bool) -> int:
        account = self.get(account_id)
        months = 0
        for record in account["contributions"]:
            if record.get("remote") and not mutual:
                continue
            months += record["consecutive_months"]
        return months

    # ---- 家庭授权 ----

    def has_family_auth(self, account_id: str, scenario: str, at: str | date) -> bool:
        on = d(at)
        for auth in self.get(account_id)["family_auths"]:
            if auth["scenario"] != scenario:
                continue
            if d(auth["granted_at"]) > on:
                continue
            revoked = auth.get("revoked_at")
            if revoked and d(revoked) <= on:
                continue
            return True
        return False

    # ---- 消费凭证 ----

    def voucher(self, account_id: str, voucher_id: str) -> dict | None:
        for voucher in self.get(account_id)["vouchers"]:
            if voucher["voucher_id"] == voucher_id:
                return voucher
        return None

    # ---- 历史提取与额度占用 ----

    def paid_usage(self, account_id: str, scenario: str, year: int) -> int:
        return sum(
            item["amount"]
            for item in self.get(account_id)["usage_history"]
            if item["scenario"] == scenario and item["year"] == year and item["state"] == "paid"
        )

    def occupied(self, account_id: str, scenario: str, year: int) -> int:
        return sum(
            item["amount"]
            for item in self.occupations
            if item["account_id"] == account_id
            and item["scenario"] == scenario
            and item["year"] == year
        )

    def last_paid_usage(self, account_id: str, scenario: str) -> date | None:
        dates = [
            d(item["used_at"])
            for item in self.get(account_id)["usage_history"]
            if item["scenario"] == scenario and item["state"] == "paid"
        ]
        return max(dates) if dates else None

    def occupy(self, case_id: str, account_id: str, scenario: str, year: int, amount: int) -> None:
        self.occupations.append(
            {"case_id": case_id, "account_id": account_id, "scenario": scenario, "year": year, "amount": amount}
        )

    def release_occupation(self, case_id: str) -> None:
        self.occupations = [item for item in self.occupations if item["case_id"] != case_id]

    # ---- 余额在途冻结（裁定时 hold，支付时扣减） ----

    def hold(self, case_id: str, account_id: str, amount: int) -> None:
        if case_id in self.holds:
            raise ValueError(f"案件 {case_id} 已有在途冻结")
        if amount > self.available_balance(account_id):
            raise ValueError("可用余额不足，无法冻结")
        self.holds[case_id] = {"account_id": account_id, "amount": amount}

    def deduct_held(self, case_id: str) -> int:
        hold = self.holds.pop(case_id)
        account = self.get(hold["account_id"])
        account["balance"] -= hold["amount"]
        return hold["amount"]

    def release_hold(self, case_id: str) -> None:
        self.holds.pop(case_id, None)

    # ---- 使用限制：骗提三年、骗贷五年 ----

    def restriction_active(self, account_id: str, at: str | date) -> dict | None:
        on = d(at)
        for restriction in self.get(account_id)["restrictions"]:
            start = d(restriction["from_date"])
            try:
                until = start.replace(year=start.year + restriction["years"])
            except ValueError:
                # 起始日为闰日 2/29，到期年无该日时落到 2/28
                until = start.replace(year=start.year + restriction["years"], day=28)
            if on < until:
                return restriction
        return None

    def add_restriction(self, account_id: str, restriction_type: str, at: str | date, years: int) -> None:
        account = self.get(account_id)
        account["restrictions"].append({"type": restriction_type, "from_date": d(at).isoformat(), "years": years})

    def record_usage(self, account_id: str, item: dict) -> None:
        self.get(account_id)["usage_history"].append(item)

    def clawback_usage(self, case_id: str) -> None:
        for account in self.accounts.values():
            for item in account["usage_history"]:
                if item["case_id"] == case_id and item["state"] == "paid":
                    item["state"] = "clawed_back"
