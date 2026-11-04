"""Deterministic demo data so the app can be explored (and screenshotted) fast."""

from __future__ import annotations

import random
from datetime import date

from .dates import month_of, recent_months, shift_month, today
from .models import DEFAULT_CATEGORIES
from .repository import Repository

_DEMO_ACCOUNTS = (
    # (name, type, opening balance in cents)
    ("招商银行储蓄卡", "debit", 1_200_000),
    ("支付宝", "debit", 1_800_000),
    ("微信钱包", "debit", 900_000),
    ("现金", "cash", 300_000),
    ("基金账户", "investment", 14_800_000),
    ("招行信用卡", "credit", 0),
    ("花呗", "credit", 0),
    ("车贷", "loan", -12_800_000),
)

_DINING_CREDIT = (
    ("星巴克", 2_800, 5_600),
    ("海底捞", 18_000, 32_000),
    ("西贝莜面村", 7_800, 13_600),
)
_DINING_ALIPAY = (
    ("美团外卖", 2_800, 6_800),
    ("盒马鲜生", 8_000, 24_000),
    ("公司食堂", 1_800, 2_800),
)
_DINING_WECHAT = (
    ("瑞幸咖啡", 1_500, 2_900),
    ("蜜雪冰城", 800, 1_800),
)
_SHOPPING_CREDIT = (
    ("京东", 9_900, 69_900),
    ("优衣库", 19_900, 59_900),
    ("山姆会员店", 12_000, 45_000),
)
_SHOPPING_HUABEI = (
    ("淘宝", 8_800, 48_000),
    ("天猫超市", 9_900, 32_000),
)
_TRANSPORT = (
    ("滴滴出行", 1_800, 6_500),
    ("地铁", 400, 1_200),
    ("中国石化", 25_000, 32_000),
)
_ENTERTAINMENT = (
    ("网易云音乐", 1_500, 1_500),
    ("猫眼电影", 6_000, 12_000),
    ("Steam", 3_800, 12_800),
)


class _DemoWriter:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo
        self.accounts: dict[str, int] = {}
        self.categories: dict[tuple[str, str], int] = {}
        self.rng = random.Random(20261029)

    def setup(self) -> None:
        self.repo.clear_all(seed_defaults=False)
        for name, kind, color in DEFAULT_CATEGORIES:
            category_id = self.repo.add_category(name, kind, color)
            self.categories[(name, kind)] = category_id
        for name, type_, opening in _DEMO_ACCOUNTS:
            self.accounts[name] = self.repo.add_account(name, type_, opening)

    def amount(self, low: int, high: int, step: int = 100) -> int:
        value = self.rng.randrange(low, high + 1)
        return max(step, value // step * step)

    def transaction(
        self,
        day: date,
        kind: str,
        amount: int,
        category: str,
        account: str,
        payee: str,
        note: str = "",
    ) -> None:
        category_id = None
        if kind != "transfer":
            category_id = self.categories[(category, kind)]
        self.repo.add_transaction(
            date=day.isoformat(),
            kind=kind,
            amount=amount,
            category_id=category_id,
            account_id=self.accounts[account],
            payee=payee,
            note=note,
        )

    def transfer(
        self, day: date, amount: int, source: str, target: str, note: str
    ) -> None:
        self.repo.add_transaction(
            date=day.isoformat(),
            kind="transfer",
            amount=amount,
            account_id=self.accounts[source],
            to_account_id=self.accounts[target],
            note=note,
        )

    def expense(
        self,
        day: date,
        amount: int,
        category: str,
        account: str,
        payee: str,
        note: str = "",
    ) -> None:
        self.transaction(day, "expense", amount, category, account, payee, note)


def seed_demo(repo: Repository) -> None:
    """Replace all data with a realistic, deterministic 12-month sample."""
    writer = _DemoWriter(repo)
    writer.setup()
    rng = writer.rng
    months = recent_months(12)
    today_value = today()

    for index, month in enumerate(months):
        year, month_number = map(int, month.split("-"))
        is_current = month == month_of(today_value)
        last_day = today_value.day if is_current else 28

        def day(number: int) -> date:
            return date(year, month_number, max(1, min(number, last_day)))

        writer.transaction(
            day(10), "income", 1_850_000, "工资", "招商银行储蓄卡",
            "星辰科技有限公司", "月度工资",
        )
        writer.expense(
            day(5), 420_000, "居住", "招商银行储蓄卡", "房东 · 陈先生", "10 月房租"
            if month_number == 10 else "月度房租",
        )
        writer.expense(
            day(12), writer.amount(26_000, 42_000, 500), "居住",
            "招商银行储蓄卡", "国家电网", "水电燃气",
        )
        writer.expense(
            day(8), 9_900, "通讯", "支付宝", "中国移动", "手机套餐",
        )
        writer.transaction(
            day(20), "income", writer.amount(25_000, 45_000, 100), "理财",
            "基金账户", "理财收益", "货币基金分红",
        )
        writer.expense(
            day(18), 30_000 + rng.randrange(0, 5000, 100), "餐饮",
            "招商银行储蓄卡", "全家便利店", "日常采购",
        )
        writer.expense(
            day(min(last_day, 7 + rng.randrange(0, 10))),
            writer.amount(45_000, 90_000),
            "购物",
            "花呗",
            "淘宝",
            "网购",
        )

        if last_day >= 18:
            writer.transfer(day(18), 100_000, "招商银行储蓄卡", "招行信用卡", "信用卡还款")
        if last_day >= 9:
            writer.transfer(day(9), 50_000, "招商银行储蓄卡", "花呗", "花呗还款")
        if last_day >= 15:
            writer.transfer(day(15), 240_000, "招商银行储蓄卡", "车贷", "车贷月供")
        if last_day >= 25:
            writer.transfer(day(25), 200_000, "招商银行储蓄卡", "基金账户", "定投转入")

        # Every-day spending, spread over the month.
        event_days = [1 + int(rng.random() * 26) for _ in range(11)]
        for event_day in sorted(event_days):
            if event_day > last_day:
                continue
            roll = rng.random()
            event_date = day(event_day)
            if roll < 0.38:
                payee, low, high = _DINING_CREDIT[rng.randrange(len(_DINING_CREDIT))]
                writer.expense(
                    event_date, writer.amount(low, high), "餐饮", "招行信用卡", payee
                )
            elif roll < 0.55:
                payee, low, high = _DINING_ALIPAY[rng.randrange(len(_DINING_ALIPAY))]
                account = "现金" if payee == "公司食堂" else "支付宝"
                writer.expense(
                    event_date, writer.amount(low, high), "餐饮", account, payee
                )
            elif roll < 0.65:
                payee, low, high = _DINING_WECHAT[rng.randrange(len(_DINING_WECHAT))]
                writer.expense(
                    event_date, writer.amount(low, high, 50), "餐饮", "微信钱包", payee
                )
            elif roll < 0.78:
                payee, low, high = _SHOPPING_CREDIT[rng.randrange(len(_SHOPPING_CREDIT))]
                writer.expense(
                    event_date, writer.amount(low, high), "购物", "招行信用卡", payee
                )
            elif roll < 0.85:
                payee, low, high = _SHOPPING_HUABEI[rng.randrange(len(_SHOPPING_HUABEI))]
                writer.expense(
                    event_date, writer.amount(low, high), "购物", "花呗", payee
                )
            elif roll < 0.94:
                payee, low, high = _TRANSPORT[rng.randrange(len(_TRANSPORT))]
                account = "微信钱包" if payee == "滴滴出行" else "支付宝"
                writer.expense(
                    event_date, writer.amount(low, high, 50), "交通", account, payee
                )
            else:
                payee, low, high = _ENTERTAINMENT[rng.randrange(len(_ENTERTAINMENT))]
                writer.expense(
                    event_date, writer.amount(low, high, 50), "娱乐", "微信钱包", payee
                )

        # A few recurring extras: medicine, coffee runs and one trip.
        if index % 3 == 1 and last_day >= 21:
            writer.expense(
                day(21), writer.amount(4_500, 18_000, 100), "医疗", "支付宝",
                "益丰大药房", "常备药",
            )
        if index == 6 and last_day >= 22:
            writer.expense(
                day(14), 128_000, "旅行", "招行信用卡", "携程旅行", "杭州周末酒店"
            )
            writer.expense(
                day(22), 186_000, "旅行", "招行信用卡", "东方航空", "往返机票"
            )

        if index >= len(months) - 3:
            repo.upsert_budget(month, 0, 800_000)
            repo.upsert_budget(month, writer.categories[("居住", "expense")], 500_000)
            repo.upsert_budget(month, writer.categories[("餐饮", "expense")], 180_000)
            repo.upsert_budget(month, writer.categories[("购物", "expense")], 120_000)
            repo.upsert_budget(month, writer.categories[("交通", "expense")], 40_000)
            repo.upsert_budget(month, writer.categories[("娱乐", "expense")], 30_000)
            repo.upsert_budget(month, writer.categories[("旅行", "expense")], 150_000)

    # Make sure the dashboard has something for the previous month too.
    previous = shift_month(month_of(today_value), -1)
    if not repo.budget_lines(previous):
        repo.upsert_budget(previous, 0, 800_000)
