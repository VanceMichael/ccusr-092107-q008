"""银行支付：并发请求幂等，同一案件最多一次真实支付。"""

import threading


class BankGateway:
    """模拟银行：以案件号为幂等键，重复/并发请求只产生一笔支付。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._settled: dict[str, dict] = {}

    def pay(self, idempotency_key: str, amount: int) -> dict:
        with self._lock:
            existing = self._settled.get(idempotency_key)
            if existing:
                return {**existing, "duplicate": True}
            result = {"bank_serial": f"B-{idempotency_key}", "amount": amount, "status": "paid", "duplicate": False}
            self._settled[idempotency_key] = result
            return dict(result)


class PaymentService:
    def __init__(self, ledger, registry, gateway: BankGateway | None = None):
        self.ledger = ledger
        self.registry = registry
        self.gateway = gateway or BankGateway()
        self.results: dict[str, dict] = {}
        self._lock = threading.Lock()

    def pay(self, case_id: str) -> dict:
        """执行或返回已有支付结果；并发调用安全。"""
        with self._lock:
            if case_id in self.results:
                return self.results[case_id]
            result = self._settle(case_id)
            self.results[case_id] = result
            self.registry.get(case_id)["payment"] = result
            return dict(result)

    def _settle(self, case_id: str) -> dict:
        case = self.registry.get(case_id)
        decision = case.get("decision")
        if not decision or decision["result"] != "approved" or decision["approved_amount"] <= 0:
            return {"case_id": case_id, "status": "skipped", "amount": 0, "bank_serial": None}
        bank = self.gateway.pay(case_id, decision["approved_amount"])
        if not bank["duplicate"]:
            paid = self.ledger.deduct_held(case_id)
            self.ledger.record_usage(
                case["account_id"],
                {
                    "case_id": case_id,
                    "scenario": case["scenario"],
                    "amount": paid,
                    "year": int(case["accepted_at"][:4]),
                    "state": "paid",
                    "used_at": decision["decided_at"],
                },
            )
            self.ledger.release_occupation(case_id)
        else:
            paid = bank["amount"]
        return {
            "case_id": case_id,
            "status": bank["status"],
            "amount": paid,
            "bank_serial": bank["bank_serial"],
        }

    def release_unpaid(self, case_id: str) -> None:
        """裁定未获支付时释放在途冻结与额度占用。"""
        if case_id not in self.results:
            self.ledger.release_hold(case_id)
            self.ledger.release_occupation(case_id)

    def real_result(self, case_id: str) -> dict | None:
        """复议可引用的唯一支付事实来源。"""
        result = self.results.get(case_id)
        if not result or result["status"] != "paid":
            return None
        return dict(result)
