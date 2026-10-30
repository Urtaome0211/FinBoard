"""Translation-layer regression tests."""

from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox, QLabel  # noqa: E402

from finboard.core.dates import (  # noqa: E402
    full_date_label,
    month_label,
    short_month_label,
    weekday_label,
)
from finboard.i18n import (  # noqa: E402
    account_type_display,
    category_display,
    currency_display,
    is_english,
    language,
    set_language,
    t,
    today_label,
)
from finboard.ui.localize import localize_widgets  # noqa: E402


class TranslationTests(unittest.TestCase):
    app: QApplication

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        set_language("zh")

    def tearDown(self) -> None:
        set_language("zh")

    def test_default_language_is_chinese(self) -> None:
        self.assertFalse(is_english())
        self.assertEqual(language(), "zh")
        self.assertEqual(t("总览"), "总览")
        self.assertEqual(t("共 {count} 笔记录", count=3), "共 3 笔记录")

    def test_english_lookup_and_templates(self) -> None:
        set_language("en")
        self.assertTrue(is_english())
        self.assertEqual(t("总览"), "Overview")
        self.assertEqual(t("共 {count} 笔记录", count=3), "3 records")
        self.assertEqual(
            t("已用 {used} · 超支 {amount}", used="¥10", amount="¥2"),
            "Used ¥10 · Over budget ¥2",
        )

    def test_display_helpers(self) -> None:
        set_language("en")
        self.assertEqual(category_display("餐饮"), "Dining")
        self.assertEqual(category_display("自定义分类"), "自定义分类")
        self.assertEqual(account_type_display("投资理财"), "Investments")
        self.assertEqual(
            currency_display("USD", "$", "美元"), "USD · $ US dollar"
        )

    def test_dates_follow_language(self) -> None:
        set_language("en")
        self.assertEqual(month_label("2026-10"), "Oct 2026")
        self.assertEqual(short_month_label("2026-10"), "Oct")
        self.assertEqual(weekday_label("2026-10-30"), "Fri")
        self.assertEqual(full_date_label("2026-10-30"), "Fri, Oct 30, 2026")
        self.assertEqual(today_label(10, 30), "Today Oct 30")

    def test_compact_amount_units(self) -> None:
        from finboard.i18n import compact_amount

        set_language("zh")
        self.assertEqual(compact_amount(2_000_000), "¥2万")
        set_language("en")
        self.assertEqual(compact_amount(2_000_000), "¥20k")
        self.assertEqual(compact_amount(250_000_000), "¥2.5M")

    def test_localizer_skips_user_content_subtrees(self) -> None:
        set_language("en")
        from PySide6.QtWidgets import QVBoxLayout, QWidget

        root = QWidget()
        layout = QVBoxLayout(root)
        edited = QLabel("总览")
        user = QLabel("支付宝")
        user.setProperty("i18nSkip", True)
        combo = QComboBox()
        combo.addItems(["总览", "支付宝"])
        combo.setProperty("i18nSkip", True)
        layout.addWidget(edited)
        layout.addWidget(user)
        layout.addWidget(combo)
        root.show()
        localize_widgets(root)
        self.assertEqual(edited.text(), "Overview")
        self.assertEqual(user.text(), "支付宝")
        self.assertEqual(combo.itemText(1), "支付宝")
        root.deleteLater()


if __name__ == "__main__":
    unittest.main()
