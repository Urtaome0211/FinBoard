import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from finboard.core.csv_io import export_csv, import_csv
from finboard.core.database import Database
from finboard.core.demo import seed_demo
from finboard.core.repository import Repository
from finboard.core.dates import month_of, today
from finboard.core.service import FinanceService


def main() -> None:
    path = Path(tempfile.gettempdir()) / "finboard_smoke.db"
    if path.exists():
        path.unlink()
    db = Database(path)
    repo = Repository(db)
    seed_demo(repo)
    service = FinanceService(repo)
    print("summary:", repo.summary_text())
    print("net worth:", repo.net_worth())
    print("month:", repo.month_stats())
    print("budgets:", [(b.name, b.amount, b.spent) for b in repo.budget_lines(month_of(today()))])
    print("trend:", [(t.month, t.income, t.expense) for t in repo.trend(12)])
    print("accounts:", [(a.name, a.balance) for a in repo.accounts()])
    print("recent:", repo.recent_transactions(3))

    csv_path = Path(tempfile.gettempdir()) / "finboard_smoke.csv"
    count = export_csv(repo, csv_path)
    result = import_csv(repo, csv_path)
    print("csv export/import:", count, result)
    print("after import:", repo.count_transactions())
    print("format:", service.format(1234567), service.percent(3, 7))
    db.close()
    path.unlink(missing_ok=True)
    csv_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
