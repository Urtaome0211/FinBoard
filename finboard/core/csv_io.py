"""CSV import / export with human-friendly Chinese headers."""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path
from typing import Iterable

from .models import KIND_LABELS, CsvRule, ImportResult, TransactionFilter
from .money import CURRENCIES, parse_amount
from .dates import normalize_day
from .repository import Repository

CSV_HEADERS = [
    "日期",
    "类型",
    "金额",
    "币种",
    "分类",
    "账户",
    "转入账户",
    "到账金额",
    "对方",
    "备注",
]

_HEADER_ALIASES = {
    "date": {"日期", "date", "时间", "交易日期"},
    "kind": {"类型", "type", "收支类型", "收支"},
    "amount": {"金额", "amount", "金额(元)", "金额（元）", "金额(分)"},
    "currency": {"币种", "currency", "货币"},
    "category": {"分类", "category", "类别"},
    "account": {"账户", "account", "支出账户", "付款账户"},
    "to_account": {"转入账户", "to_account", "目标账户", "对方账户", "收款账户"},
    "to_amount": {"到账金额", "to_amount", "转入金额"},
    "payee": {"对方", "商户", "payee", "merchant", "交易对方"},
    "note": {"备注", "note", "说明", "memo"},
}

_KIND_ALIASES = {
    "支出": "expense",
    "消费": "expense",
    "付款": "expense",
    "expense": "expense",
    "out": "expense",
    "收入": "income",
    "收款": "income",
    "income": "income",
    "in": "income",
    "转账": "transfer",
    "转帐": "transfer",
    "transfer": "transfer",
}


def _amount_text(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    value = abs(cents)
    return f"{sign}{value // 100}.{value % 100:02d}"


def export_csv(
    repo: Repository,
    path: str | Path,
    filters: TransactionFilter | None = None,
) -> int:
    """Write transactions (newest first) to a UTF-8 BOM CSV file. Returns row count."""
    filters = filters or TransactionFilter(limit=100_000)
    rows = repo.transactions(filters)
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_HEADERS)
        for txn in rows:
            writer.writerow(
                [
                    txn.date,
                    KIND_LABELS[txn.kind],
                    _amount_text(txn.amount),
                    txn.currency,
                    txn.category_name,
                    txn.account_name,
                    txn.to_account_name,
                    _amount_text(txn.to_amount) if txn.to_amount else "",
                    txn.payee,
                    txn.note,
                ]
            )
    return len(rows)


def _decode(raw: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("无法识别文件编码，请另存为 UTF-8 或 GBK 编码的 CSV")


def _map_header(name: str) -> str | None:
    clean = str(name or "").replace("\ufeff", "").strip().lower()
    for key, aliases in _HEADER_ALIASES.items():
        if clean in aliases:
            return key
    return None


CSV_FIELDS = (
    "date",
    "kind",
    "amount",
    "currency",
    "category",
    "account",
    "to_account",
    "to_amount",
    "payee",
    "note",
)


def _implicit_mapping(headers: list[str]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for header in headers:
        field = _map_header(header)
        if field and field not in mapping:
            mapping[field] = header
    return mapping


def _import_hash(
    date_value: str,
    kind: str,
    amount: int,
    currency: str,
    account_name: str,
    to_account_name: str,
    payee: str,
) -> str:
    raw = "|".join(
        (
            date_value,
            kind,
            str(int(amount)),
            currency.upper(),
            account_name.strip().casefold(),
            to_account_name.strip().casefold(),
            payee.strip().casefold(),
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def read_headers(path: str | Path) -> list[str]:
    text = _decode(Path(path).read_bytes())
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    try:
        return [str(cell).replace("\ufeff", "").strip() for cell in next(reader)]
    except StopIteration:
        raise ValueError("CSV 文件为空") from None


def _open_rows(text: str) -> tuple[list[str], list[dict[str, str]]]:
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(text), dialect)
    raw_rows = list(reader)
    if not raw_rows:
        raise ValueError("CSV 文件为空")
    headers = [str(cell).replace("\ufeff", "").strip() for cell in raw_rows[0]]
    records: list[dict[str, str]] = []
    for raw in raw_rows[1:]:
        if not any(cell.strip() for cell in raw):
            continue
        record = {
            headers[index]: cell.strip()
            for index, cell in enumerate(raw)
            if index < len(headers) and headers[index]
        }
        records.append(record)
    return headers, records


def import_csv(
    repo: Repository,
    path: str | Path,
    *,
    rule: CsvRule | None = None,
    dedup: bool = True,
) -> ImportResult:
    """Validate every row, then import the good ones in a single transaction."""
    text = _decode(Path(path).read_bytes())
    headers, rows = _open_rows(text)
    if rule and rule.mapping:
        mapping = {
            field: source
            for field, source in rule.mapping.items()
            if field in CSV_FIELDS and source in headers
        }
    else:
        mapping = _implicit_mapping(headers)
    missing = [field for field in ("date", "kind", "amount", "account") if field not in mapping]
    if missing:
        raise ValueError(
            "列映射缺少必需字段：日期、类型、金额、账户；请先设置 CSV 规则"
        )

    def value(row: dict[str, str], field: str) -> str:
        source = mapping.get(field)
        return row.get(source, "").strip() if source else ""

    accounts = {
        account.name.strip().casefold(): account
        for account in repo.accounts(include_archived=True)
    }
    categories = {
        (category.name.strip().casefold(), category.kind): category
        for category in repo.categories()
    }

    result = ImportResult()
    prepared: list[dict] = []
    seen_hashes: set[str] = set()
    for index, row in enumerate(rows, start=2):
        try:
            raw_date = value(row, "date")
            if not raw_date:
                raise ValueError("缺少日期")
            date_value = normalize_day(raw_date)

            kind_name = value(row, "kind")
            kind = _KIND_ALIASES.get(kind_name.casefold()) or _KIND_ALIASES.get(kind_name)
            if not kind:
                raise ValueError(f"无法识别的类型“{kind_name}”")

            amount = parse_amount(value(row, "amount"))
            if amount <= 0:
                raise ValueError("金额必须大于 0")

            currency = (value(row, "currency") or "CNY").upper()
            if currency not in CURRENCIES:
                raise ValueError(f"不支持的币种“{currency}”")

            account_name = value(row, "account")
            account = accounts.get(account_name.casefold())
            if account is None:
                raise ValueError(f"账户“{account_name}”不存在")
            if account.archived:
                raise ValueError(f"账户“{account_name}”已归档")
            try:
                account_amount = repo._converted(
                    amount, currency, account.currency, date_value
                )
            except ValueError as exc:
                raise ValueError(str(exc)) from None

            category_id = None
            to_account_id = None
            to_amount = None
            target_name = ""
            if kind == "transfer":
                target_name = value(row, "to_account")
                target = accounts.get(target_name.casefold())
                if target is None:
                    raise ValueError(f"转入账户“{target_name}”不存在")
                if target.id == account.id:
                    raise ValueError("转入与转出账户不能相同")
                if target.archived:
                    raise ValueError(f"转入账户“{target_name}”已归档")
                to_account_id = target.id
                raw_to_amount = value(row, "to_amount")
                if raw_to_amount:
                    to_amount = parse_amount(raw_to_amount)
                else:
                    try:
                        to_amount = repo._converted(
                            amount, currency, target.currency, date_value
                        )
                    except ValueError as exc:
                        raise ValueError(str(exc)) from None
            else:
                category_name = value(row, "category")
                category = categories.get((category_name.casefold(), kind))
                if category is None:
                    raise ValueError(f"分类“{category_name}”不存在于{KIND_LABELS[kind]}分类")
                category_id = category.id

            payee = value(row, "payee")[:60]
            import_hash = _import_hash(
                date_value,
                kind,
                amount,
                currency,
                account_name,
                target_name,
                payee,
            )
            if dedup and (
                import_hash in seen_hashes
                or repo.import_hash_exists(import_hash)
                or repo.transaction_matches(
                    date=date_value,
                    kind=kind,
                    amount=amount,
                    currency=currency,
                    account_id=account.id,
                    to_account_id=to_account_id,
                    payee=payee,
                )
            ):
                result.duplicates += 1
                continue
            seen_hashes.add(import_hash)
            prepared.append(
                {
                    "date": date_value,
                    "kind": kind,
                    "amount": amount,
                    "currency": currency,
                    "account_amount": account_amount,
                    "to_amount": to_amount,
                    "category_id": category_id,
                    "account_id": account.id,
                    "to_account_id": to_account_id,
                    "payee": payee,
                    "note": value(row, "note")[:200],
                    "import_hash": import_hash if dedup else None,
                }
            )
        except ValueError as exc:
            result.skipped += 1
            if len(result.errors) < 50:
                result.errors.append(f"第 {index} 行：{exc}")

    if prepared:
        result.imported = repo.insert_normalized(prepared)
    return result
