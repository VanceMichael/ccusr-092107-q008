"""申请受理：线上与窗口去重、撤回重提、补件中止。"""

from .timeutil import d, decision_deadline, suspension_open


class CaseError(Exception):
    pass


def _dedup_key(submission: dict) -> tuple:
    return (
        submission["person_id"],
        submission["scenario"],
        submission["housing_city_code"],
        submission.get("housing_id", ""),
        submission.get("period", ""),
    )


class CaseRegistry:
    """登记受理申请，保证线上与窗口重复提交合并为同一案件。"""

    def __init__(self):
        self.cases: dict[str, dict] = {}
        self._key_to_case: dict[tuple, str] = {}

    def submit(self, submission: dict) -> dict:
        """受理一笔提交；重复提交只追加渠道，不产生新案件、不改变受理时点。"""
        key = _dedup_key(submission)
        existing_id = self._key_to_case.get(key)
        if existing_id:
            case = self.cases[existing_id]
            if case["status"] == "withdrawn":
                raise CaseError("原申请已撤回，应走撤回重提，不能重复受理")
            case["channels"].append(submission["channel"])
            return case

        case = {
            "case_id": submission["case_id"],
            "person_id": submission["person_id"],
            "account_id": submission["account_id"],
            "scenario": submission["scenario"],
            "housing_city_code": submission["housing_city_code"],
            "accepted_at": submission["submitted_at"],
            "request_amount": submission["request_amount"],
            "voucher_id": submission.get("voucher_id"),
            "channels": [submission["channel"]],
            "status": "pending",
            "suspensions": [],
            "policy_snapshot": None,
            "decision": None,
            "withdrawn_at": None,
            "origin_case_id": None,
        }
        self.cases[case["case_id"]] = case
        self._key_to_case[key] = case["case_id"]
        return case

    def get(self, case_id: str) -> dict:
        return self.cases[case_id]

    def withdraw(self, case_id: str, at: str) -> dict:
        case = self.get(case_id)
        if case["status"] not in ("pending", "supplement"):
            raise CaseError("已作出决定的申请不能撤回")
        case["status"] = "withdrawn"
        case["withdrawn_at"] = at
        return case

    def resubmit(self, origin_case_id: str, at: str, channel: str) -> dict:
        """撤回后重提：沿用原受理时点与原政策版本，仅恢复办理。"""
        origin = self.get(origin_case_id)
        if origin["status"] != "withdrawn":
            raise CaseError("只有已撤回的申请可以重提")
        case_id = f"{origin_case_id}-R"
        if case_id in self.cases:
            raise CaseError("重提申请已存在")
        renewed = dict(origin)
        renewed.update(
            {
                "case_id": case_id,
                "status": "pending",
                "withdrawn_at": None,
                "origin_case_id": origin_case_id,
                "accepted_at": origin["accepted_at"],
                "channels": [channel],
                "suspensions": list(origin["suspensions"]),
            }
        )
        self.cases[case_id] = renewed
        return renewed

    # ---- 补件中止 ----

    def suspend_for_supplement(self, case_id: str, start: str) -> dict:
        case = self.get(case_id)
        if suspension_open(case["suspensions"]):
            raise CaseError("已有未结束的补件中止")
        case["suspensions"].append({"start": start, "end": None, "reason": "补件"})
        case["status"] = "supplement"
        return case

    def resume_from_supplement(self, case_id: str, end: str) -> dict:
        case = self.get(case_id)
        for interval in reversed(case["suspensions"]):
            if interval["end"] is None:
                if d(end) < d(interval["start"]):
                    raise CaseError("恢复日期不能早于中止日期")
                interval["end"] = end
                case["status"] = "pending"
                return case
        raise CaseError("没有进行中的补件中止")

    def deadline(self, case_id: str):
        case = self.get(case_id)
        return decision_deadline(case["accepted_at"], case["suspensions"])
