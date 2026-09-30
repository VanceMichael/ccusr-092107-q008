"""裁定引擎：按受理时间与住房所在地裁定，各入口保持一致。

一致性规则：
- 线上与窗口重复提交同一笔业务时返回在办件，不重复立案；
- 跨城转移冻结的余额不可提取；
- 同一裁定只支付一次（见 payments.PaymentLedger）；
- 撤回后可重新提交，新申请按新的受理时间解析政策版本；
- 骗提追缴后账户记入限制记录，期限年限由受理时点的政策版本给出；
- 补件依法中止的时间从三日办理期限中扣除（见 deadline 模块）。
"""

import threading
from dataclasses import replace
from datetime import datetime, timedelta

from . import deadline
from .domain import (
    Account,
    Application,
    AppStatus,
    Decision,
    RestrictionRecord,
    SupplementRequest,
    Suspension,
    WithdrawalRecord,
)
from .payments import PaymentLedger, PaymentRecord, RecoveryRecord
from .policy import PolicyBook, PolicyVersion

_OCCUPANCY_WINDOW = timedelta(days=365)


def _restricted_until(recorded_at: datetime, years: int) -> datetime:
    try:
        return recorded_at.replace(year=recorded_at.year + years)
    except ValueError:  # 2 月 29 日
        return recorded_at.replace(year=recorded_at.year + years, day=28)


class Adjudicator:
    def __init__(
        self,
        book: PolicyBook,
        accounts: dict[str, Account],
        ledger: PaymentLedger | None = None,
    ) -> None:
        self.book = book
        self.accounts = accounts
        self.ledger = ledger or PaymentLedger()
        self.apps: dict[str, Application] = {}
        self.status: dict[str, AppStatus] = {}
        self.suspensions: dict[str, list[Suspension]] = {}
        self.decisions: dict[str, Decision] = {}  # app_id -> Decision
        self._decision_ids: dict[str, Decision] = {}
        self._by_business_key: dict[tuple, str] = {}
        self._pay_lock = threading.Lock()

    # ---- 受理 ----

    def submit(self, app: Application) -> tuple[str, bool]:
        """登记申请；返回 (申请编号, 是否新立)。重复提交返回在办件编号。"""
        existing = self._by_business_key.get(app.business_key)
        if existing is not None and self.status[existing] in (
            AppStatus.PENDING,
            AppStatus.SUPPLEMENT,
        ):
            return existing, False
        self.apps[app.app_id] = app
        self.status[app.app_id] = AppStatus.PENDING
        self.suspensions[app.app_id] = []
        self._by_business_key[app.business_key] = app.app_id
        return app.app_id, True

    # ---- 裁定 ----

    def adjudicate(self, app_id: str, now: datetime) -> Decision | SupplementRequest:
        """按受理时点的政策版本裁定；政策修订不影响在办件。"""
        if self.status[app_id] != AppStatus.PENDING:
            raise ValueError("只有待裁定申请可以裁定")
        app = self.apps[app_id]
        policy = self.book.resolve(app.city, app.accepted_at.date())
        account = self.accounts[app.applicant_id]
        kind, amount, reasons = self.evaluate(app, policy, account)
        if kind == "supplement":
            return self._open_supplement(app_id, reasons, now)
        outcome = AppStatus.APPROVED if kind == "approve" else AppStatus.REJECTED
        decision = Decision(
            decision_id=f"D-{app_id}",
            app_id=app_id,
            outcome=outcome,
            amount=amount,
            reasons=tuple(reasons),
            policy_city=policy.city,
            policy_version=policy.version,
            decided_at=now,
        )
        self.status[app_id] = outcome
        self.decisions[app_id] = decision
        self._decision_ids[decision.decision_id] = decision
        return decision

    def evaluate(
        self, app: Application, policy: PolicyVersion, account: Account
    ) -> tuple[str, int, list[str]]:
        """纯规则求值：返回 (approve|reject|supplement, 金额, 理由)。

        裁定与复议共用此函数，区别只在政策版本的选取方式。
        """
        reasons: list[str] = []
        for rec in account.restrictions:
            years = policy.restriction_years.get(rec.kind)
            if years is None:
                continue
            until = _restricted_until(rec.recorded_at, years)
            if app.accepted_at < until:
                reasons.append(f"{rec.kind}限制期至{until.date()}未满")
        if reasons:
            return "reject", 0, reasons

        rule = policy.scenarios.get(app.scenario.value)
        if rule is None:
            return "reject", 0, [f"{app.scenario.value}不属于受理情形"]

        missing: list[str] = []
        if rule.requires_family_auth and not app.family_auth:
            missing.append("家庭授权")
        if rule.requires_vouchers and not app.vouchers:
            missing.append("消费凭证")
        if missing:
            return "supplement", 0, missing

        window_start = app.accepted_at - _OCCUPANCY_WINDOW
        used = sum(
            w.amount
            for w in account.withdrawals
            if w.house_id == app.house_id
            and w.scenario == app.scenario
            and window_start <= w.paid_at <= app.accepted_at
        )
        quota = rule.annual_limit - used
        if quota <= 0:
            return "reject", 0, ["年度额度已被历史提取占用"]
        if account.available <= 0:
            return "reject", 0, ["账户可用余额不足（含转移冻结）"]
        amount = min(app.amount, quota, account.available)
        return "approve", amount, []

    # ---- 补件 ----

    def _open_supplement(
        self, app_id: str, missing: list[str], now: datetime
    ) -> SupplementRequest:
        self.status[app_id] = AppStatus.SUPPLEMENT
        self.suspensions[app_id].append(Suspension(start=now))
        return SupplementRequest(app_id, tuple(missing), now)

    def supplement(
        self,
        app_id: str,
        now: datetime,
        *,
        family_auth: bool | None = None,
        vouchers: tuple[str, ...] | None = None,
    ) -> None:
        """补齐材料：中止区间结束，申请回到待裁定，仍按原受理时间裁定。"""
        if self.status[app_id] != AppStatus.SUPPLEMENT:
            raise ValueError("只有补件中止中的申请可以补件")
        open_susp = self.suspensions[app_id][-1]
        if open_susp.end is not None:
            raise ValueError("中止区间已关闭")
        open_susp.end = now
        app = self.apps[app_id]
        self.apps[app_id] = replace(
            app,
            family_auth=app.family_auth if family_auth is None else family_auth,
            vouchers=app.vouchers if vouchers is None else vouchers,
        )
        self.status[app_id] = AppStatus.PENDING

    def processing_remaining(self, app_id: str, now: datetime) -> timedelta:
        """三日办理期限的剩余时间，已扣除补件中止区间。"""
        app = self.apps[app_id]
        return deadline.remaining(app.accepted_at, self.suspensions[app_id], now)

    # ---- 撤回与重提 ----

    def withdraw(self, app_id: str) -> None:
        """撤回申请；之后同一业务可重新提交，按新的受理时间裁定。"""
        if self.status[app_id] not in (AppStatus.PENDING, AppStatus.SUPPLEMENT):
            raise ValueError("只有在办申请可以撤回")
        self.status[app_id] = AppStatus.WITHDRAWN

    # ---- 支付与追缴 ----

    def pay_approved(self, decision_id: str, now: datetime) -> PaymentRecord:
        """执行支付；同一裁定并发或重复调用只支付一次。"""
        decision = self._decision_ids[decision_id]
        if decision.outcome != AppStatus.APPROVED:
            raise ValueError("只有批准的裁定可以支付")
        with self._pay_lock:
            existing = self.ledger.find(decision_id)
            if existing is not None:
                return existing
            app = self.apps[decision.app_id]
            account = self.accounts[app.applicant_id]
            account.balance -= decision.amount
            account.withdrawals.append(
                WithdrawalRecord(app.house_id, app.scenario, decision.amount, now)
            )
            return self.ledger.pay(decision_id, decision.amount, now)

    def recover_fraud(self, decision_id: str, now: datetime) -> RecoveryRecord:
        """骗提追缴：退回资金并记入限制记录，后续申请按政策版本受限。"""
        payment = self.ledger.find(decision_id)
        if payment is None:
            raise ValueError("没有支付记录，无法追缴")
        decision = self._decision_ids[decision_id]
        app = self.apps[decision.app_id]
        account = self.accounts[app.applicant_id]
        with self._pay_lock:
            if not self.ledger.is_recovered(decision_id):
                account.balance += payment.amount
                account.restrictions.append(RestrictionRecord("骗提骗贷", now))
            return self.ledger.recover(decision_id, payment.amount, now)

    # ---- 查询 ----

    def decision_by_id(self, decision_id: str) -> Decision:
        return self._decision_ids[decision_id]
