"""测试共享的构建工具：从样例资料装配裁定引擎。"""

from pathlib import Path

from src.adjudication import Adjudicator
from src.domain import Application, Channel, Scenario
from src.store import load_accounts, load_policy_book

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"


def make_adjudicator() -> Adjudicator:
    book = load_policy_book(FIXTURES / "policies.json")
    accounts = load_accounts(FIXTURES / "accounts.json")
    return Adjudicator(book, accounts)


def make_app(app_id, applicant_id, *, accepted_at, amount=25000, house_id="house-01",
             city="示例市", scenario=Scenario.RENOVATION, channel=Channel.WINDOW,
             family_auth=True, vouchers=("v-1",)):
    return Application(
        app_id=app_id,
        applicant_id=applicant_id,
        house_id=house_id,
        city=city,
        scenario=scenario,
        amount=amount,
        channel=channel,
        accepted_at=accepted_at,
        family_auth=family_auth,
        vouchers=vouchers,
    )
