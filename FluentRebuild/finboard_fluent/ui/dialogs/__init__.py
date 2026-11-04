"""Modal forms used by the main window."""

from .account_dialog import AccountDialog
from .budget_dialog import BudgetDialog
from .bulk_edit import BulkEditDialog
from .category_dialog import CategoryDialog
from .category_manager import CategoryManagerDialog
from .category_rules import CategoryRulesDialog
from .csv_import import CsvImportDialog
from .debt_dialog import DebtDialog
from .debt_schedule_dialog import DebtScheduleDialog, PayoffDialog
from .deposit_dialog import DepositDialog
from .fixed_asset_dialog import FixedAssetDialog
from .fixed_cost import FixedCostDialog
from .goal_dialog import GoalDepositDialog, GoalDialog
from .holdings_dialog import HoldingDialog, HoldingsDialog
from .metadata_dialog import MetadataDialog
from .planned_dialog import PlannedDialog
from .receivable_dialog import ReceivableDialog
from .reconcile_dialog import ReconcileDialog
from .recurring_dialog import RecurringDialog
from .transaction_dialog import TransactionDialog
from .valuation_dialog import ValuationDialog

__all__ = [
    "AccountDialog",
    "BudgetDialog",
    "BulkEditDialog",
    "CategoryDialog",
    "CategoryManagerDialog",
    "CategoryRulesDialog",
    "CsvImportDialog",
    "DebtDialog",
    "DebtScheduleDialog",
    "DepositDialog",
    "FixedAssetDialog",
    "FixedCostDialog",
    "GoalDepositDialog",
    "GoalDialog",
    "HoldingDialog",
    "HoldingsDialog",
    "MetadataDialog",
    "PayoffDialog",
    "PlannedDialog",
    "ReceivableDialog",
    "ReconcileDialog",
    "RecurringDialog",
    "TransactionDialog",
    "ValuationDialog",
]
