"""Render the report to PDF with Qt's text document engine (no extra deps)."""

from __future__ import annotations

import html
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from ..core.dates import month_label, today_iso
from ..core.models import KIND_LABELS, TransactionFilter
from ..core.repository import Repository


def _money(cents: int) -> str:
    return f"¥{cents / 100:,.2f}"


def _rows(repo: Repository, month: str | None) -> str:
    rows = repo.transactions(TransactionFilter(month=month, limit=100_000))
    parts = []
    for txn in rows:
        tags = " ".join(f"#{tag.name}" for tag in txn.tags)
        parts.append(
            "<tr>"
            f"<td width='13%' class='nw'>{html.escape(txn.date)}</td>"
            f"<td width='8%'>{html.escape(KIND_LABELS.get(txn.kind, txn.kind))}</td>"
            f"<td width='15%' class='r nw'>{_money(txn.amount)} {html.escape(txn.currency)}</td>"
            f"<td width='18%'>{html.escape(txn.category_name or '—')}</td>"
            f"<td width='22%'>{html.escape(txn.account_name)}</td>"
            f"<td width='15%'>{html.escape(txn.payee or txn.note or '')}</td>"
            f"<td width='9%'>{html.escape(tags)}</td>"
            "</tr>"
        )
    return "".join(parts)


def export_pdf(repo: Repository, path: str | Path, month: str | None = None) -> Path:
    target = Path(path)
    net = repo.net_worth()
    stats = repo.month_stats(month)
    breakdown = repo.category_breakdown(month, "expense")
    total = sum(item.amount for item in breakdown) or 1
    categories = "".join(
        f"<tr><td width='50%'>{html.escape(item.name)}</td>"
        f"<td width='28%' class='r'>{_money(item.amount)}</td>"
        f"<td width='22%' class='r'>{item.amount / total * 100:.1f}%</td></tr>"
        for item in breakdown[:12]
    )
    period = month_label(month) if month else "全部月份"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    document_html = f"""
    <html><head><style>
    body {{ font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif; color: #172033; }}
    h1 {{ font-size: 22pt; margin: 0 0 2pt 0; color: #172033; }}
    .sub {{ color: #667085; font-size: 9pt; margin-bottom: 14pt; }}
    .cards {{ width: 100%; margin-bottom: 16pt; }}
    .cards td {{ padding: 8pt; background: #F5F7FB; border: 1pt solid #E8EDF5; }}
    .label {{ color: #667085; font-size: 8pt; }}
    .value {{ font-size: 13pt; font-weight: bold; }}
    h2 {{ font-size: 12pt; margin: 14pt 0 6pt 0; }}
    table.data {{ width: 100%; border-collapse: collapse; font-size: 8.5pt; }}
    table.data th {{ background: #EEF3FF; color: #26406F; text-align: left; padding: 4pt; border: 0.5pt solid #E8EDF5; }}
    table.data td {{ border: 0.5pt solid #E8EDF5; padding: 3.5pt; }}
    .r {{ text-align: right; }}
    .nw {{ white-space: nowrap; }}
    .muted {{ color: #667085; font-size: 8pt; }}
    </style></head><body>
    <h1>FinBoard 财务报表</h1>
    <div class='sub'>统计期间：{html.escape(period)} · 导出时间：{generated}</div>
    <table class='cards'><tr>
    <td><div class='label'>资产</div><div class='value'>{_money(net.assets)}</div></td>
    <td><div class='label'>负债</div><div class='value'>{_money(net.liabilities)}</div></td>
    <td><div class='label'>净资产</div><div class='value'>{_money(net.net)}</div></td>
    <td><div class='label'>本月收入 / 支出</div><div class='value'>{_money(stats.income)} / {_money(stats.expense)}</div></td>
    </tr></table>
    <h2>支出分类</h2>
    <table class='data' width='100%' cellspacing='0' cellpadding='4'>
    <tr><th width='50%'>分类</th><th width='28%' class='r'>金额</th><th width='22%' class='r'>占比</th></tr>{categories}</table>
    <h2>收支明细</h2>
    <table class='data' width='100%' cellspacing='0' cellpadding='4'>
    <tr><th width='13%'>日期</th><th width='8%'>类型</th><th width='15%' class='r'>金额</th><th width='18%'>分类</th><th width='22%'>账户</th><th width='15%'>对方</th><th width='9%'>标签</th></tr>
    {_rows(repo, month)}
    </table>
    <p class='muted'>转账、手续费与拆分均按报表口径展示；本报表由 FinBoard 本机生成。</p>
    </body></html>
    """
    writer = QPdfWriter(str(target))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Unit.Millimeter)
    writer.setResolution(96)
    writer.setTitle("FinBoard 财务报表")
    writer.setCreator("FinBoard")
    document = QTextDocument()
    document.setDefaultFont(QFont("Microsoft YaHei UI", 9))
    document.setHtml(document_html)
    document.print_(writer)
    return target


def pdf_filename() -> str:
    return f"FinBoard-报表-{today_iso()}.pdf"
