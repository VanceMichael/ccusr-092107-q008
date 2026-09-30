"""领域对象：申请、账户、补件中止区间、裁定与支付相关记录。"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Channel(str, Enum):
    ONLINE = "线上"
    WINDOW = "窗口"


class Scenario(str, Enum):
    RENOVATION = "装修"
    PROPERTY_FEE = "物业费"
    AGING_RENOVATION = "适老化改造"
    ELEVATOR = "加装电梯"


class AppStatus(str, Enum):
    PENDING = "待裁定"
    SUPPLEMENT = "补件中止"
    APPROVED = "已批准"
    REJECTED = "已拒绝"
    WITHDRAWN = "已撤回"


@dataclass(frozen=True)
class Application:
    """一笔提取申请；受理时间决定适用的政策版本。"""

    app_id: str
    applicant_id: str  # 与账户编号一致（样例均为虚构值）
    house_id: str
    city: str  # 住房所在地，裁定按此地政策
    scenario: Scenario
    amount: int  # 申请金额（元）
    channel: Channel
    accepted_at: datetime  # 受理时间
    family_auth: bool = False
    vouchers: tuple[str, ...] = ()

    @property
    def business_key(self) -> tuple:
        """同一申请人就同一住房同一场景的提交视为同一笔业务。"""
        return (self.applicant_id, self.house_id, self.scenario.value)


@dataclass
class Suspension:
    """补件依法中止的区间；end 为 None 表示仍在中止中。"""

    start: datetime
    end: datetime | None = None


@dataclass(frozen=True)
class WithdrawalRecord:
    """历史提取记录，用于核算年度额度占用。"""

    house_id: str
    scenario: Scenario
    amount: int
    paid_at: datetime


@dataclass(frozen=True)
class RestrictionRecord:
    """使用限制记录；期限年限由受理时点的政策版本给出。"""

    kind: str  # 如 违法提取 / 骗提骗贷
    recorded_at: datetime


@dataclass
class Account:
    """缴存账户；frozen 为跨城转移等原因冻结的金额。"""

    account_id: str
    balance: int
    frozen: int = 0
    withdrawals: list[WithdrawalRecord] = field(default_factory=list)
    restrictions: list[RestrictionRecord] = field(default_factory=list)

    @property
    def available(self) -> int:
        """可用余额：冻结部分不可提取。"""
        return self.balance - self.frozen


@dataclass(frozen=True)
class Decision:
    """裁定结果；记录所依据的政策版本，供复议引用。"""

    decision_id: str
    app_id: str
    outcome: AppStatus  # 仅 APPROVED 或 REJECTED
    amount: int  # 批准金额（元），拒绝时为 0
    reasons: tuple[str, ...]
    policy_city: str
    policy_version: int
    decided_at: datetime


@dataclass(frozen=True)
class SupplementRequest:
    """补件通知；发出即依法中止办理期限。"""

    app_id: str
    missing: tuple[str, ...]
    requested_at: datetime
