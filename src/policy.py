"""按城市与生效区间管理政策版本，裁定只读取受理时点的版本。

政策版本库只增不改：同一城市的同一版本号不允许改写，
生效区间不得重叠。裁定发生时按（住房所在地， 受理日期）解析，
即使裁定日晚于新政策生效日，也仍适用受理时点的旧版本。
"""

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ScenarioRule:
    """单一提取情形在一个政策版本下的规则。"""

    annual_limit: int  # 同一住房每年可提额度（元）
    requires_vouchers: bool  # 是否需要消费凭证
    requires_family_auth: bool  # 是否需要家庭授权


@dataclass(frozen=True)
class PolicyVersion:
    """某城市一段生效区间内的完整政策。"""

    city: str
    version: int
    effective_from: date
    effective_to: date | None  # 半开区间 [effective_from, effective_to)
    scenarios: dict[str, ScenarioRule]
    restriction_years: dict[str, int]  # 违法提取 3 年、骗提骗贷 5 年等

    def covers(self, day: date) -> bool:
        return self.effective_from <= day and (
            self.effective_to is None or day < self.effective_to
        )


class PolicyBook:
    """只增不改的政策版本库。"""

    def __init__(self) -> None:
        self._versions: list[PolicyVersion] = []

    def add(self, version: PolicyVersion) -> None:
        for old in self._versions:
            if old.city != version.city:
                continue
            if old.version == version.version:
                if old != version:
                    raise ValueError("同一城市同一版本号不允许改写")
                return  # 幂等重放
            if old.covers(version.effective_from) or version.covers(
                old.effective_from
            ):
                raise ValueError("同一城市的生效区间不得重叠")
        self._versions.append(version)

    def resolve(self, city: str, day: date) -> PolicyVersion:
        """返回指定日期生效的版本；裁定应传入受理日期而非裁定日期。"""
        for v in self._versions:
            if v.city == city and v.covers(day):
                return v
        raise LookupError(f"{city} 在 {day} 没有生效的政策版本")

    def get(self, city: str, version: int) -> PolicyVersion:
        """按编号取回历史版本，供复议引用原裁定版本。"""
        for v in self._versions:
            if v.city == city and v.version == version:
                return v
        raise LookupError(f"{city} 没有版本 {version}")
