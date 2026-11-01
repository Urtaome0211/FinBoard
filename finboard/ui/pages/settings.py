"""Preferences, data tools and app information."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from ... import __app_name__, __app_name_cn__, __version__
from ...i18n import currency_display, language, t
from ...core.money import CURRENCIES
from ..dialogs import CategoryManagerDialog, CategoryRulesDialog, CsvImportDialog
from ..localize import localize_widgets
from ..theme import theme_mode, theme_store
from ..widgets import (
    Card,
    ComboBox,
    ConfirmDialog,
    Page,
    PageHeader,
    SegmentedControl,
    ThemedButton,
)

if TYPE_CHECKING:
    from ..main_window import MainWindow


class SettingsPage(Page):
    def __init__(self, service, window: "MainWindow") -> None:
        super().__init__()
        self.service = service
        self.window = window

        header = PageHeader("设置", "外观、语言、货币、分类与本地数据")
        self.header = header
        self.body.addWidget(header)

        self._build_language()
        self._build_appearance()
        self._build_currency()
        self._build_rates()
        self._build_categories()
        self._build_data()
        self._build_about()
        self.body.addStretch(1)

        self._update_rate_labels()
        theme_store.changed.connect(self._sync_theme)

    # ------------------------------------------------------------------
    def _row(self, title: str, hint: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(18)
        text = QVBoxLayout()
        text.setSpacing(2)
        label = QLabel(title)
        label.setStyleSheet("font-weight: 600;")
        text.addWidget(label)
        detail = QLabel(hint)
        detail.setProperty("role", "muted")
        detail.setWordWrap(True)
        text.addWidget(detail)
        row.addLayout(text, 1)
        return row

    def _build_language(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add_header("语言", "界面语言切换后立即生效，默认中文")
        row = self._row("界面语言", "English / 中文")
        self.language_control = SegmentedControl(
            [("中文", "zh"), ("English", "en")], language()
        )
        self.language_control.setProperty("i18nSkip", True)
        self.language_control.setFixedWidth(220)
        self.language_control.changed.connect(self.window.set_language)
        row.addWidget(self.language_control)
        card.body.addLayout(row)
        self.body.addWidget(card)

    def _build_appearance(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add_header("外观", "扁平化界面，两套配色")
        row = self._row("主题模式", "切换后立即生效，偏好会被记住。")
        self.theme_control = SegmentedControl(
            [("浅色", "light"), ("深色", "dark")], theme_mode()
        )
        self.theme_control.setFixedWidth(200)
        self.theme_control.changed.connect(self.window.set_theme)
        row.addWidget(self.theme_control)
        card.body.addLayout(row)
        self.body.addWidget(card)

    def _build_currency(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add_header("货币", "基准币种用于总览、报表与预算汇总")
        row = self._row(
            "基准币种",
            "账户按各自币种记账；汇总时按交易日期汇率折算为基准币种。切换前需先更新汇率。",
        )
        self.currency_combo = ComboBox()
        self.currency_combo.setMinimumWidth(230)
        for code, info in CURRENCIES.items():
            self.currency_combo.addItem(
                currency_display(code, info["symbol"], info["name"]), code
            )
        index = self.currency_combo.findData(self.service.currency)
        if index >= 0:
            self.currency_combo.setCurrentIndex(index)
        self.currency_combo.currentIndexChanged.connect(self._currency_changed)
        row.addWidget(self.currency_combo)
        card.body.addLayout(row)
        self.body.addWidget(card)

    def _build_rates(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add_header("汇率", "每日自动更新 · 来源 Frankfurter（ECB 参考汇率）")
        row = self._row(
            "每日汇率",
            "外币记账按交易发生日的汇率折算；周末和节假日沿用最近一个工作日。",
        )
        self.rate_button = ThemedButton("更新汇率", "soft", "refresh")
        self.rate_button.clicked.connect(self._refresh_rates)
        row.addWidget(self.rate_button)
        card.body.addLayout(row)

        self.rate_status = QLabel()
        self.rate_status.setProperty("role", "muted")
        self.rate_status.setWordWrap(True)
        card.body.addWidget(self.rate_status)

        self.rate_detail = QLabel()
        self.rate_detail.setProperty("role", "faint")
        self.rate_detail.setWordWrap(True)
        card.body.addWidget(self.rate_detail)
        self.body.addWidget(card)

    def _refresh_rates(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self.rate_button.setEnabled(False)
        try:
            self.service.refresh_rates(force=True)
            self.window.notify("汇率已更新")
        except Exception as exc:  # network / parse / storage errors all surface here
            ConfirmDialog.alert(self, "汇率更新失败", str(exc), icon_name="alert")
        finally:
            QApplication.restoreOverrideCursor()
            self.rate_button.setEnabled(True)
            self.refresh()

    def _update_rate_labels(self) -> None:
        store = self.service.rate_store
        latest = store.latest_date()
        if not latest:
            self.rate_status.setText(t("尚未更新汇率；外币交易需要先更新。"))
            self.rate_detail.setText("")
            return
        error = store.last_error()
        if error:
            status = t(
                "最新汇率日期：{date} · 来源 Frankfurter/ECB（上次更新失败，当前使用缓存）",
                date=latest,
            )
        else:
            status = t(
                "最新汇率日期：{date} · 来源 Frankfurter/ECB", date=latest
            )
        self.rate_status.setText(status)
        try:
            rates = store.rates_for(latest)
        except Exception:
            rates = {}
        pieces = []
        for code in CURRENCIES:
            if code == "CNY" or code not in rates:
                continue
            pieces.append(f"1 CNY = {rates[code]:.4f} {code}")
        self.rate_detail.setText("  ·  ".join(pieces))

    def _build_categories(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add_header("分类", "支出与收入分类")
        row = self._row(
            "管理分类",
            "重命名、改颜色或删除分类；删除后相关记录会移到「其他」。",
        )
        manage = ThemedButton("管理分类", "secondary", "tag")
        manage.clicked.connect(self._manage_categories)
        row.addWidget(manage)
        card.body.addLayout(row)

        rules_row = self._row(
            "自动分类规则",
            "按付款对象匹配分类与标签，可在记账时自动填充，也可从历史记录学习。",
        )
        rules = ThemedButton("管理规则", "secondary", "sparkles")
        rules.clicked.connect(self._manage_rules)
        rules_row.addWidget(rules)
        card.body.addLayout(rules_row)
        self.body.addWidget(card)

    def _build_data(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add_header("数据", "全部保存在本机 SQLite 数据库中")
        self.data_folder = Path(self.service.repo.db.path).parent
        row = self._row("数据目录", str(self.data_folder))
        open_dir = ThemedButton("打开目录", "secondary", "database")
        open_dir.clicked.connect(self._open_data_dir)
        row.addWidget(open_dir)
        card.body.addLayout(row)

        path = QLineEdit(str(self.service.repo.db.path))
        path.setReadOnly(True)
        path.setCursorPosition(0)
        card.body.addWidget(path)

        actions = QHBoxLayout()
        actions.setSpacing(10)
        export_button = ThemedButton("导出全部 CSV", "soft", "download")
        import_button = ThemedButton("导入 CSV", "soft", "upload")
        backup_button = ThemedButton("备份数据库", "ghost", "shield")
        export_button.clicked.connect(self._export)
        import_button.clicked.connect(self._import)
        backup_button.clicked.connect(self._backup)
        for button in (export_button, import_button, backup_button):
            actions.addWidget(button)
        actions.addStretch(1)
        card.body.addLayout(actions)

        auto_row = self._row(
            "自动备份",
            "启动时检查数据库完整性，并在超过 20 小时未备份时自动创建快照。",
        )
        self.backup_auto = SegmentedControl(
            [("启用", True), ("停用", False)],
            bool(self.window.settings.value("backup/auto", True, type=bool)),
        )
        self.backup_auto.setFixedWidth(180)
        self.backup_auto.changed.connect(self._backup_auto_changed)
        auto_row.addWidget(self.backup_auto)
        card.body.addLayout(auto_row)

        self.backup_label = QLabel()
        self.backup_label.setProperty("role", "faint")
        self.backup_label.setWordWrap(True)
        card.body.addWidget(self.backup_label)

        backup_actions = QHBoxLayout()
        backup_actions.setSpacing(10)
        backup_now = ThemedButton("立即备份", "soft", "shield")
        restore = ThemedButton("从备份恢复…", "ghost", "database")
        check = ThemedButton("检查完整性", "ghost", "check")
        backup_now.clicked.connect(self._backup_now)
        restore.clicked.connect(self._restore_backup)
        check.clicked.connect(self._check_integrity)
        backup_actions.addWidget(backup_now)
        backup_actions.addWidget(restore)
        backup_actions.addWidget(check)
        backup_actions.addStretch(1)
        card.body.addLayout(backup_actions)

        hint = QLabel(
            "导入按「日期,类型,金额,分类,账户,转入账户,对方,备注」表头解析，"
            "支持 UTF-8 与 GB18030 编码；无法识别的行会被跳过并给出原因。"
        )
        hint.setProperty("role", "faint")
        hint.setWordWrap(True)
        card.body.addWidget(hint)
        self._update_backup_label()
        self.body.addWidget(card)

    def _build_about(self) -> None:
        card = Card(padding=20, spacing=14)
        card.add_header("演示与重置", "数据迁移前建议先备份或导出")
        row = self._row(
            "演示数据",
            "生成 12 个月的示例账户与交易，用来快速体验图表。会替换当前全部数据。",
        )
        demo = ThemedButton("载入演示数据", "secondary", "sparkles")
        demo.clicked.connect(self._load_demo)
        row.addWidget(demo)
        card.body.addLayout(row)

        danger_row = self._row(
            "清空数据",
            "删除所有账户、交易、预算和自定义分类，恢复为初始状态。此操作不可撤销。",
        )
        clear = ThemedButton("清空全部数据", "danger", "trash")
        clear.clicked.connect(self._clear)
        danger_row.addWidget(clear)
        card.body.addLayout(danger_row)
        self.body.addWidget(card)

        about = Card(padding=20, spacing=10)
        about.add_header("关于", f"{__app_name__} · {__app_name_cn__}")
        blurb = QLabel(
            "一个纯本地、零云端依赖的个人财务管理工具。"
            "Qt 界面与全部图表均自绘，金额以整数“分”存储和计算。"
        )
        blurb.setWordWrap(True)
        blurb.setProperty("role", "muted")
        about.body.addWidget(blurb)
        meta = QLabel(
            f"{t('版本 {version}', version=__version__)}   ·   PySide6 / SQLite   ·   MIT License"
        )
        meta.setProperty("role", "faint")
        about.body.addWidget(meta)
        shortcuts = QLabel(
            "快捷键：Ctrl+N 记一笔 · Ctrl+F 搜索 · Ctrl+Z 撤销上一步 · "
            "Ctrl+1…5 切换页面 · Ctrl+, 设置"
        )
        shortcuts.setProperty("role", "faint")
        shortcuts.setWordWrap(True)
        about.body.addWidget(shortcuts)
        self.body.addWidget(about)

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        index = self.currency_combo.findData(self.service.currency)
        if index >= 0 and index != self.currency_combo.currentIndex():
            self.currency_combo.blockSignals(True)
            self.currency_combo.setCurrentIndex(index)
            self.currency_combo.blockSignals(False)
        self._update_rate_labels()
        self._update_backup_label()

    def _sync_theme(self) -> None:
        mode = theme_mode()
        if self.theme_control.value() != mode:
            self.theme_control.set_value(mode)

    def _currency_changed(self, _index: int) -> None:
        code = self.currency_combo.currentData()
        if code and code != self.service.currency:
            try:
                self.window.set_currency(code)
            except ValueError as exc:
                ConfirmDialog.alert(self, "无法切换币种", str(exc), icon_name="alert")
                self.refresh()

    def _manage_categories(self) -> None:
        CategoryManagerDialog(self.service, self.window).exec()

    def _manage_rules(self) -> None:
        dialog = CategoryRulesDialog(self.service, self.window)
        localize_widgets(dialog)
        dialog.exec()

    def _backup_auto_changed(self, value: object) -> None:
        self.window.settings.setValue("backup/auto", bool(value))
        self.window.settings.sync()

    def _update_backup_label(self) -> None:
        try:
            backups = self.service.backups()
        except OSError:
            backups = []
        if not backups:
            self.backup_label.setText(t("最近备份：尚无自动备份"))
            return
        latest = backups[0]
        stamp = datetime.fromtimestamp(latest.stat().st_mtime).strftime(
            "%Y-%m-%d %H:%M"
        )
        self.backup_label.setText(
            t("最近备份：{name} · {time}", name=latest.name, time=stamp)
        )

    def _backup_now(self) -> None:
        try:
            target = self.service.create_backup(keep=10)
        except (OSError, ValueError) as exc:
            ConfirmDialog.alert(self, "备份失败", str(exc), icon_name="alert")
            return
        self._update_backup_label()
        self.window.notify(t("备份已创建：{name}", name=target.name))

    def _restore_backup(self) -> None:
        try:
            backups = self.service.backups()
        except OSError:
            backups = []
        folder = backups[0].parent if backups else self.data_folder
        path, _filter = QFileDialog.getOpenFileName(
            self, "从备份恢复", str(folder), "SQLite 数据库 (*.db)"
        )
        if not path:
            return
        if not ConfirmDialog.confirm(
            self,
            "从备份恢复？",
            "当前数据库会被所选备份覆盖。恢复前会自动为当前数据创建一份快照。",
            ok_text="恢复",
            danger=True,
            icon_name="database",
        ):
            return
        try:
            self.service.restore_backup(path)
        except (OSError, ValueError) as exc:
            ConfirmDialog.alert(self, "恢复失败", str(exc), icon_name="alert")
            return
        self._update_backup_label()
        self.window.refresh_all()
        self.window.notify(t("已从备份恢复"))

    def _check_integrity(self) -> None:
        try:
            ok, detail = self.service.check_integrity()
        except (OSError, ValueError) as exc:
            ConfirmDialog.alert(self, "检查失败", str(exc), icon_name="alert")
            return
        if ok:
            self.window.notify(t("数据库检查通过"))
            return
        ConfirmDialog.alert(
            self,
            "数据库检查失败",
            detail or t("数据库完整性检查未通过。"),
            icon_name="alert",
        )

    def _open_data_dir(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.data_folder)))

    def _export(self) -> None:
        desktop = Path.home() / "Desktop"
        folder = desktop if desktop.exists() else Path.home()
        default = folder / f"FinBoard-导出-{datetime.now():%Y%m%d}.csv"
        path, _filter = QFileDialog.getSaveFileName(
            self, "导出全部记录", str(default), "CSV 文件 (*.csv)"
        )
        if not path:
            return
        try:
            count = self.service.export_csv(path)
        except (OSError, ValueError) as exc:
            ConfirmDialog.alert(self, "导出失败", str(exc), icon_name="alert")
            return
        self.window.notify(f"已导出 {count} 条记录")

    def _import(self) -> None:
        dialog = CsvImportDialog(self.service, self)
        dialog.exec()

    def _backup(self) -> None:
        desktop = Path.home() / "Desktop"
        folder = desktop if desktop.exists() else Path.home()
        default = folder / f"FinBoard-备份-{datetime.now():%Y%m%d-%H%M}.db"
        path, _filter = QFileDialog.getSaveFileName(
            self, "备份数据库", str(default), "SQLite 数据库 (*.db)"
        )
        if not path:
            return
        try:
            target = sqlite3.connect(path)
            try:
                self.service.repo.db.conn.backup(target)
            finally:
                target.close()
        except (OSError, sqlite3.Error) as exc:
            ConfirmDialog.alert(self, "备份失败", str(exc), icon_name="alert")
            return
        self.window.notify("数据库备份完成")

    def _load_demo(self) -> None:
        if not ConfirmDialog.confirm(
            self,
            "载入演示数据？",
            "当前全部账户、交易和预算会被示例数据替换。建议先导出 CSV 或备份。",
            ok_text="载入演示",
            icon_name="sparkles",
        ):
            return
        self.service.seed_demo()
        self.window.notify("演示数据已载入")

    def _clear(self) -> None:
        if not ConfirmDialog.confirm(
            self,
            "清空全部数据？",
            "所有账户、交易、预算和自定义分类都会被删除，无法恢复。\n"
            "建议先导出 CSV 或备份数据库。",
            ok_text="全部清空",
            danger=True,
            icon_name="trash",
        ):
            return
        self.service.clear_all()
        self.window.notify("数据已清空")
