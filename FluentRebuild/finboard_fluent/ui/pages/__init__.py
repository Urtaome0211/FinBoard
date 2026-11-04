"""Application pages."""

from .accounts import AccountsPage
from .budgets import BudgetsPage
from .dashboard import DashboardPage
from .debts import DebtsPage
from .fixed_assets import FixedAssetsPage
from .forecast import ForecastPage
from .planned import PlannedPage
from .receivables import ReceivablesPage
from .recurring import RecurringPage
from .reports import ReportsPage
from .savings import SavingsPage
from .settings import SettingsPage
from .transactions import TransactionsPage

__all__ = [
    "AccountsPage",
    "BudgetsPage",
    "DashboardPage",
    "DebtsPage",
    "FixedAssetsPage",
    "ForecastPage",
    "PlannedPage",
    "ReceivablesPage",
    "RecurringPage",
    "ReportsPage",
    "SavingsPage",
    "SettingsPage",
    "TransactionsPage",
]
