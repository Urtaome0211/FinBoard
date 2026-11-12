# 用 PySide6-Fluent-Widgets 重构 FinBoard：一次“只换壳”的实践

## 一、背景

FinBoard（财观）是一个本地优先的个人财务桌面应用：Python + PySide6 + SQLite，图表全部用 QPainter 手绘。到 5.0 时，功能已经比较完整：账户、收支、预算、负债、固定资产、储蓄、计划、往来款、定期、预测、报表、导入导出、托盘提醒、自动备份……

但界面一直是“自绘 QSS”风格：侧栏是 `QWidget` + `QPushButton` 拼出来的，标题栏是自定义的，弹窗是普通 `QDialog`。功能没问题，视觉和 Windows 11 的原生应用差距明显。

这次的目标不是重写业务，而是验证一件事：

> 在**不改数据层、不破坏既有功能**的前提下，把桌面壳换成 Fluent 风格，需要付出多少成本？

最终选了 **PySide6-Fluent-Widgets 1.11.3**，在 `FluentRebuild/` 里做了一个独立包 `finboard_fluent`，与 5.0 共用数据库，交付源码和 Windows one-dir 包。

## 二、约束与目标

开始前先定了几条边界：

1. **完整功能对齐 5.0**：13 个页面、11 类对话框、快捷键、托盘、提醒、撤销、退款、导入、报表都不能少。
2. **独立包名**：`finboard_fluent`，避免和原 `finboard` 包在同一环境里冲突。
3. **共用数据库**：仍然打开 `%LOCALAPPDATA%\FinBoard\finboard.db`，schema 保持 15。
4. **不改坏 5.0**：原项目继续可用，重构全部放在 `FluentRebuild/`。
5. **发布方式**：最终版本 5.3.0 按要求打包并发布到 GitHub Releases；开发过程中不提前上传。

这几条决定了策略：**只换壳，不换业务**。`core/` 原样复制，页面布局尽量复用，主窗口、导航、标题栏、提示条重写。

## 三、为什么是 PySide6-Fluent-Widgets

候选大概有三类：

- **qfluentwidgets / PySide6-Fluent-Widgets**：组件最全，`FluentWindow` 自带标题栏、导航、Mica、主题；缺点是版本更新快，部分 API 和文档对不上。
- **自己画 Fluent 风格 QSS**：可控，但标题栏、Mica、导航指示器这些细节很难做得像。
- **换到 QML / Qt Quick**：视觉上限高，但等于重写全部页面，成本不可接受。

选 qfluentwidgets 的决定性因素是 `FluentWindow`：它把标题栏、导航、堆叠页面、窗口控制都封装好了，接入成本远低于自己实现。版本锁在 **1.11.3**，避免上游 API 漂移。

依赖上踩了一个坑：一开始用 `pip install --target FluentRebuild_vendor`，把整套 PySide6 也装进了 vendor。结果离屏启动时报：

```text
QFontDatabase: Cannot find font directory .../FluentRebuild_vendor/PySide6/lib/fonts
```

原因是 vendor 里的 PySide6 是复制安装，字体目录不完整。后来改成系统环境安装 `PySide6-Fluent-Widgets==1.11.3`，复用已有的 PySide6 6.12.0，问题消失。**不要在一个项目里塞两份 PySide6。**

## 四、整体架构

重构后的目录：

```text
FluentRebuild/
├─ finboard_fluent/
│  ├─ app.py
│  ├─ core/            # 与 5.0 同源
│  ├─ ui/
│  │  ├─ main_window.py
│  │  ├─ pages/        # 13 个页面
│  │  ├─ dialogs/      # 11 类对话框
│  │  ├─ charts.py
│  │  └─ theme.py
│  ├─ locales/en.json
│  └─ resources/
├─ tests/
├─ run.py
├─ FinBoardFluent.spec
└─ requirements.txt
```

`main_window.py` 从 `QMainWindow` 换成 `FluentWindow`，页面本身仍是原来的 `Page` 子类。这样页面内部不需要知道外壳换了，`self.window` 仍然可用。

### 4.1 导航

13 个页面通过 `addSubInterface` 注册：

```python
self.addSubInterface(page, icon, t(title))
```

设置页固定在底部：

```python
self.addSubInterface(
    page,
    FluentIcon.SETTING,
    t("设置"),
    NavigationItemPosition.BOTTOM,
)
```

导航初始展开：

```python
self.navigationInterface.setExpandWidth(250)
self.navigationInterface.setMinimumExpandWidth(900)
self.navigationInterface.expand(useAni=False)
```

图标需要做映射。`FluentIcon` 没有 `WALLET`、`TARGET`、`TRENDING_UP`、`CHART`、`SETTINGS`，所以用语义接近的图标替代，例如：

- 总览 → `HOME`
- 收支 → `DOCUMENT`
- 账户 → `FOLDER`
- 负债 → `CERTIFICATE`
- 固定资产 → `TILES`
- 预算 → `PIE_SINGLE`
- 储蓄 → `LEAF`
- 计划 → `CALENDAR`
- 往来款 → `PEOPLE`
- 预测 → `TRENDING_UP` 的替代（`MARKET`）
- 定期 → `SYNC`
- 报表 → `PIE_SINGLE` / `DOCUMENT`
- 设置 → `SETTING`

### 4.2 标题栏

`FluentWindow` 的标题栏是 `FluentTitleBar`，内部有一个 `hBoxLayout`。在 `addSubInterface` 之后、窗口显示之前插入控件：

```python
bar = self.titleBar
self.search = SearchLineEdit(self)
self.search.setPlaceholderText(t("搜索交易…"))
self.search.setFixedWidth(220)
self.add_button = PrimaryPushButton(FluentIcon.ADD, t("记一笔"), self)
self.currency_button = PushButton(...)
self.theme_button = TransparentToolButton(FluentIcon.BRIGHTNESS, self)
bar.insertWidget(2, self.search)
bar.insertWidget(3, self.add_button)
bar.insertWidget(4, self.currency_button)
bar.insertWidget(5, self.theme_button)
```

`insertWidget` 的索引依赖 `FluentTitleBar` 内部布局，升级 qfluentwidgets 时需要重新确认。这是重构里最“脆”的一处。

### 4.3 导航高亮不跟随

第一版切换页面时用 `switchTo(page)`，内容变了，但左侧导航的指示器仍停在上一项。原因是 `switchTo` 只切堆叠页，不负责更新 `NavigationInterface` 的当前项。

修复：

```python
self.navigationInterface.setCurrentItem(page.objectName())
self.switchTo(page)
```

页面注册时 `objectName` 是 `page_dashboard` 这类字符串，正好对应 `addSubInterface` 的 route key。

但同时要补一个反向同步：用户直接点导航时，`current_key` 不会更新，后续 Ctrl+F、Ctrl+Z 的行为会落在错误的页面。于是监听堆叠页变化：

```python
self.stackedWidget.currentChanged.connect(self._on_page_changed)

def _on_page_changed(self, index: int) -> None:
    widget = self.stackedWidget.widget(index)
    if widget is None:
        return
    key = widget.objectName().removeprefix("page_")
    if key in self.pages:
        self.current_key = key
```

### 4.4 主题、Mica 与离屏截图

5.0 有一套自己的 `apply_theme()`：设置 `theme_store`、生成 QSS、刷新图表调色板。Fluent 也有 `setTheme()`。两者必须同时调用：

```python
def set_theme(self, mode: str) -> None:
    self.settings.setValue("theme", mode)
    apply_theme(QApplication.instance(), mode)   # 页面/QSS/图表
    setTheme(Theme.DARK if mode == "dark" else Theme.LIGHT)
    setThemeColor("#3D6DF2")
    self._update_theme_button()
```

Mica 是这次最迷惑的问题。离屏截图时，`FluentWindow` 默认启用 Mica，透明标题栏被合成到白底上，结果：

- 亮色主题正常；
- 暗色主题标题栏和导航变白，深色文字几乎看不见。

一开始以为是 QSS 冲突，后来发现是 `setMicaEffectEnabled` 的默认值：在 Windows 上 `FluentWindow` 会自动启用 Mica，即使当前是 `QT_QPA_PLATFORM=offscreen`。修复是显式按环境设置：

```python
use_mica = (
    sys.platform == "win32"
    and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
)
self.setMicaEffectEnabled(use_mica)
```

真实 Windows 上保留 Mica；离屏和截图用纯色背景。验证暗色时一定要同时检查 `isMicaEffectEnabled()`，不能只看 `setMicaEffectEnabled(False)` 有没有调用。

### 4.5 提示条

5.0 的 `notify()` 是自己在主窗口底部画一个 toast，2.6 秒后淡出。Fluent 版改成 `InfoBar`：

```python
def notify(self, text: str) -> None:
    bar = InfoBar.success(
        title=t("提示"),
        content=text,
        orient=Qt.Horizontal,
        isClosable=True,
        position=InfoBarPosition.TOP_RIGHT,
        duration=2600,
        parent=self,
    )
```

好处是位置、动画、关闭按钮都由组件负责；代价是 `InfoBar` 在窗口很窄时可能超出边界，需要限制文本长度。

### 4.6 托盘与关闭

`closeEvent` 保留 5.0 的行为：托盘可用且用户没有主动退出时，隐藏窗口而不是退出。Fluent 版的托盘菜单、`_check_reminders()`、到期/预算/还款提醒都原样保留，只是入口从自绘按钮换成了标题栏和导航。

## 五、页面复用的边界

页面内部仍然是 5.0 的 `Page`、`Card`、`ThemedButton`、`CategoryBars`、`TrendChart`。这意味着：

- 页面标题、卡片、表格、按钮的 QSS 还是 5.0 的；
- 只有外层导航、标题栏、提示条是 Fluent 的；
- 视觉上是“Fluent 壳 + 紧凑内容”的混搭。

为什么不全部换掉？

1. 页面里有大量自定义绘制（环图、折线、热力日历、进度条），换成 Fluent 组件要重写绘图；
2. 5.0 的 132 个测试直接覆盖这些页面，全部替换会引入大量回归；
3. 这次的目标是验证壳层重构的成本，不是做一次完整设计系统迁移。

代价也要说清楚：如果你期待“每个按钮都是 Fluent 按钮”，这个版本还不满足。它是一个**可用的、功能对齐的过渡版本**，不是最终视觉形态。

## 六、语言与 i18n

5.0 的 i18n 机制是“中文原文作为 key，查 `en.json`”。Fluent 壳新增的标题栏、导航、空状态又引入了新的中文文案，所以需要补 key。

流程：

1. 用 AST 扫描 `finboard_fluent/ui` 里的 `t("…")` 中文字面量；
2. 和 `en.json` 的 key 做差集；
3. 批量补英文；
4. 再扫描一次，确认缺失为 0。

这次补了 46 个 key，`en.json` 到 1283 条。导航文字不能只靠 `localize_widgets`，因为 `NavigationInterface` 的 item 不是普通 `QLabel`，需要按 route key 取出来手动 `setText`：

```python
item = self.navigationInterface.widget(f"page_{key}")
if item is not None:
    item.setText(t(title))
```

语言切换后，标题栏按钮、搜索占位符、导航、页面正文要一起刷新；否则会出现“导航英文、内容中文”的半吊子状态。

### 6.1 从英文切回中文：翻译是不可逆的

第二版试运行时发现一个更隐蔽的问题：英文切回中文后，界面仍然显示英文。原因不复杂——5.0 的 `localize_widgets` 只在英文模式下把中文原文替换成英文；它不会保存中文原文。等切回中文时，`localize_widgets` 直接返回，widget 上只剩下英文，已经没有“原文”可以恢复。

这不是补一个反向字典就能解决的：带占位符的动态文案、运行时拼接的日期/计数、导航 item 的标题，都可能在英文状态下被重新构造。要可靠恢复，必须从“中文源字符串”重新构建控件树。

最终方案是**重建主窗口**，而不是原地刷新：

1. 保存当前页面 key、窗口几何、是否最大化；
2. 写入 `language` 设置，切换全局语言和字体；
3. 用同一 `FinanceService` / `QSettings` 构造新的 `MainWindow`；
4. 恢复几何、显示、导航回原页面；
5. 停掉旧窗口的汇率后台拉取线程，再隐藏、关闭、`deleteLater` 旧窗口。

两个坑：旧窗口的 `QTimer.singleShot(1200, self._auto_refresh_rates)` 可能在窗口关闭后才触发，必须用 `_quitting` 守卫；`QThread` 还在跑时删除旧窗口会让 Qt 直接报 `QThread: Destroyed while thread is still running`，所以重建前要 `wait()` 并清理。

测试也改成真正的往返：`zh → en → zh`，不仅断言导航文字，还断言 dashboard 页里的 `QLabel` 从 `Overview` 回到 `总览`，并确认英文标签已经消失。

## 七、测试与验证

### 7.1 测试迁移

把 `tests/` 复制过来后，把所有 `from finboard` 改成 `from finboard_fluent`。5.0 的 132 个测试全部通过，说明业务层复制没有引入行为差异。

新增 `tests/test_fluent_ui.py`，3 个测试：

1. 13 个页面都存在，逐个 `navigate` 后 `stackedWidget.currentWidget()` 正确；
2. `set_language("en")` 后导航显示 Overview/Settings，标题栏按钮显示 Add transaction；
3. `set_theme("dark")` 后页面仍然可切换，不崩溃。

5.0 初次交付时合计 **135 tests OK**；5.1 为 **158 tests OK**；5.2 为 **171 tests OK**；5.3 为 **173 tests OK**；5.3.1 为 **175 tests OK**。

### 7.2 页面与对话框冒烟

离屏渲染 13 个页面，代表性截图已放在 `docs/screenshots/`。

再构造 11 类对话框：

```text
TransactionDialog, AccountDialog, CategoryDialog, BudgetDialog,
CategoryManagerDialog, DebtDialog, PlannedDialog, ReceivableDialog,
DepositDialog, FixedCostDialog, CategoryRulesDialog
```

全部能显示、无异常；对话框截图在验证时生成，未纳入交付。

### 7.3 打包验证

PyInstaller 构建 one-dir：

```bash
python -m PyInstaller FinBoardFluent.spec --noconfirm --clean
```

验证：

```text
dist/FinBoardFluent/FinBoardFluent.exe --version  → finboard-fluent 5.0.0（5.0 历史包）
--smoke-test（离屏、临时库）                      → exit 0
```

`FinBoardFluent.spec` 的关键是收集 qfluentwidgets 的运行时资源：

```python
datas += collect_data_files("qfluentwidgets")
hiddenimports += collect_submodules("qfluentwidgets")
hiddenimports += ["qframelesswindow", "darkdetect", "PySide6.QtSvg"]
```

漏掉这些，源码能跑，打包后会报 `ModuleNotFoundError` 或图标/样式缺失。

## 八、踩坑清单

| 问题 | 现象 | 解决 |
| --- | --- | --- |
| vendor 里重复 PySide6 | 离屏启动报字体目录缺失 | 改为系统安装 qfluentwidgets，复用系统 PySide6 |
| 导航指示器不跟随 | 内容切了，左侧还高亮上一项 | `setCurrentItem(page.objectName())` |
| 用户点导航后 `current_key` 不更新 | Ctrl+F 仍搜上一个页面 | 监听 `stackedWidget.currentChanged` |
| Mica 在离屏下默认开启 | 暗色标题栏/导航发白 | 显式 `setMicaEffectEnabled(False)`（离屏） |
| 标题栏插入控件靠索引 | 升级后可能错位 | 锁定 1.11.3，升级时重测 |
| 导航文字不随语言变 | 导航中文、内容英文 | 按 route key 取 item 手动 `setText` |
| 复制测试后 import 找不到 | `No module named finboard` | 全局替换为 `finboard_fluent` |
| 打包漏 qfluentwidgets 数据 | 运行时报模块/资源错误 | spec 里 collect_data_files/submodules |

## 九、结果与取舍

已完成：

- Fluent 主壳、导航、标题栏、InfoBar；
- 13 个页面全部可切换；
- 11 类对话框可构造；
- 亮/暗主题、中/英双语；
- 托盘、提醒、快捷键、撤销、退款、复制上一笔保留；
- 173 个测试通过；
- Windows one-dir 包可运行。

没有做：

- 页面内部控件的全面 Fluent 化；
- 对话框换成 `qfluentwidgets.Dialog`；
- 自动行情、自定义模板、全局迷你输入窗。

这些不是“忘了”，而是刻意把范围收在“壳层重构 + 功能对齐”。如果继续做，下一步应该优先把对话框统一成 Fluent `Dialog`，再把页面里的 `QPushButton/QLineEdit/QComboBox` 替换成 qfluentwidgets 对应控件——这会是一次更大的视觉改造，测试也要相应调整。

## 十、经验

1. **先锁依赖版本**。qfluentwidgets 迭代快，标题栏内部结构、构造参数都可能变；锁 1.11.3，升级时单独做兼容测试。
2. **壳层重构要保留页面契约**。页面只依赖 `Page` 和 `window`，换外壳时几乎不用改页面。
3. **主题要双写**。旧 QSS 和 Fluent 主题是两套系统，必须同时更新；只改一边会出现“壳变了、图表还是旧配色”。
4. **离屏截图要关 Mica**。Windows 上默认开启，透明合成在离屏环境不可靠。
5. **导航是状态机**。`switchTo`、`setCurrentItem`、`current_key` 三处要同步，否则快捷键和搜索会串页。
6. **测试迁移是最便宜的回归保险**。132 个测试原样通过，比重新点一遍页面更可靠。

## 十一、5.1：从界面重构到核心模型补齐

界面稳定之后，5.1 没有再动壳层，而是补四块更靠近“财务模型”的能力。它们也暴露了重构项目真正的风险：**迁移、金额拆分和报表口径**。

### 11.1 数据可靠性：启动时修索引，而不是让用户看到错误

某次真实库启动时 `PRAGMA quick_check` 报 `wrong # of entries in index idx_transactions_refund`。索引损坏不是数据损坏，`REINDEX` 就能修复；但对用户来说，弹“完整性检查未通过”会被理解成数据丢了。

做法是只在错误文本命中 `index/索引` 时自动修复：

```python
def repair_indexes(db):
    if not looks_like_index_problem(quick_check(db)[1]):
        return False, ""
    create_backup(db, keep=20, reason="before-reindex")
    db.conn.execute("REINDEX")
    db.conn.commit()
    return quick_check(db)
```

修复前先备份，修复后重跑 `quick_check`；非索引错误仍然走原来的“从备份恢复”提示，不自动冒险。这个边界很重要：**自动修复只处理可证明安全的一类问题**。

### 11.2 投资逐笔流水：持仓不再是“快照”，而是流水的结果

原来的 `holdings` 是成本/数量快照，卖出时直接改数字，无法回答“这笔盈利是哪一批买的”。5.1 增加 `investment_trades`、`investment_lots`、`investment_disposals`，按 `(acquired_date, id)` FIFO 消耗批次。

关键账目：

- 买入：`gross = (qty * price + 500000) // 1000000`，`total_cost = gross + fee`，`unit_cost = round(total_cost * 1e6 / qty)`；
- 卖出：逐 lot 写 disposal，`cost_total` 求和，`realized = proceeds - cost_total`；
- 分红：只写 trade，累加 `holdings.dividends`。

迁移时把旧 `holdings` 每行写成一条 `buy` trade 和一个 lot，保证老库升级后持仓不为空。这里踩过的坑是：`transactions.import_hash` 有唯一索引且不排除空串，内部转账必须写 `NULL`，不能写 `''`。

### 11.3 负债还款：本金和利息要拆开

负债页以前只有“欠多少”，没有“还了多少”。5.1 新增 `debt_payments`，每笔还款拆成本金和利息：

- 贷款月息：`(outstanding * rate_bp + 60000) // 120000`；
- 信用卡：利息为 0，本金=还款额；
- 还款额超过“剩余本金 + 本期利息”拒绝；
- 利息不足时允许只付息，本金为 0。

本金部分创建“资金来源 → 负债账户”的转账，利息部分创建“利息支出”支出。这样账户余额、收支报表和负债余额三处口径一致，结清也不会污染支出。

### 11.4 报表查询层：任意区间、同比环比和年度 PDF

月度报表只能看单月，5.1 在报表页加了“区间分析”卡：

- 任意起止日期；
- 环比（上一等长区间）和同比（去年同区间）；
- 分类/标签/账户三种维度；
- 区间预设写入 `QSettings`；
- 年度报告 PDF 复用 Qt 的 `QTextDocument`，不引入新依赖。

实现上没有改 SQL 聚合，而是复用 `transactions()` 的 hydrated 行，再用 Python 汇总。退款按负数冲减支出，拆分按各分类金额计入，转账手续费单独成项。这样逻辑和 `month_stats` 一致，但代码更直白；代价是大区间会多读一些行，个人账本规模下可以接受。

### 11.5 这一轮的教训

1. **迁移必须可回填**。schema 15→16 的持仓回填、16→17 的还款表，都要能在真实旧库上跑通。
2. **金额拆分要有唯一口径**。还款、退款、拆分、手续费，任何一个口径不一致，报表就会对不上。
3. **自动修复要保守**。只修索引，不猜数据；修前备份，修后复检。
4. **UI 复用不等于不测**。旧 QSS 对话框在新壳里仍要构造、截图、跑交互冒烟。
5. **退出路径也要测**。`--smoke-test` 的 1200ms 退出和汇率刷新线程撞在一起，Windows 上表现为 exit 127（`0xC0000409`），日志里只有一句 `QThread: Destroyed while thread is still running`。修复不是“把线程 wait 一下”这么简单：新增 `MainWindow.shutdown()` 统一停线程，smoke 模式下直接禁用网络刷新，保证测试快且确定。

## 十二、5.2：行情、模板与快速记账

5.2 的三个需求看起来是“小功能”，但它们分别代表了三种不同的复杂度。

### 12.1 行情：网络、解析和缓存要分开

行情的第一版把 HTTP、GBK 解析、数据库更新和 UI 刷新放在同一条调用链里。结果是：网络一慢，界面就卡；刷新失败还会把“没有行情”误报成错误。最终拆成三层：

- `core/quotes.py`：只做代码归一、腾讯接口请求和 GBK 响应解析，返回 `Quote`。
- `Service`：把行情写入持仓、写缓存、发 `changed`；UI 线程只做展示。
- `QThread`：启动时或手动刷新时，网络请求在后台线程执行，失败静默保留旧价格。

一个容易忽略的细节是**腾讯接口返回的是 GBK**，不是 UTF-8；另一个是价格单位是“元”，而数据库统一用“分”。这两个转换只要有一个漏掉，界面就会显示乱码或 100 倍误差。

测试里还踩了一个 Qt 的坑：用 `QTest.qWait()` 等后台线程时，GIL 不释放，线程看起来永远不结束；换成 `processEvents() + sleep()` 才能真实验证。这不是业务 bug，但会浪费很多排查时间。

### 12.2 模板：把“重复录入”变成数据结构

模板不是简单记住上一次输入，而是一张独立的 `transaction_templates` 表：名称、类型、金额、币种、分类、账户、转入账户、对方、备注。记账对话框顶部多一个模板下拉，选中后一次性填表，日期改为今天。

模板的校验比想象中多：类型必须是支出/收入/转账；金额不能为负；分类必须和类型匹配；转账不能带分类；账户不能是系统自动创建的定期存款账户；转入账户不能和转出账户相同。这些规则和普通交易保持一致，否则模板会成为一个“绕过校验”的入口。

### 12.3 快速记账：全局快捷键是平台能力，不是 Qt 能力

Qt 没有跨平台的全局快捷键。Windows 下用 `RegisterHotKey` + `QAbstractNativeEventFilter`，注册 `Ctrl+Alt+N`；失败时回退到应用内 `QShortcut`。这样即使快捷键被其他软件占用，应用仍然可用。

快速记账窗口只保留金额、账户、分类、对方、日期、备注，回车即保存；它复用自动分类规则和“上次账户/分类”，但不复制完整记账对话框的退款、拆分、手续费等复杂字段。**快速录入不是完整记账的替代品**，而是把最高频的路径缩短到 3 个字段。

这一轮还修了一个小但典型的问题：账户下拉的余额用了 `CNY5,000.00`，而不是 `¥5,000.00`。原因是 `format_cents` 的第二个参数是“符号”，不是“币种代码”；这类显示问题很难靠单元测试发现，只能靠截图和真实数据。

### 12.4 这一轮的边界

5.2 没有做：行情历史 K 线、自动交易、自由报表设计器、跨平台全局快捷键。它们都不是“再写一个按钮”能解决的，应该作为独立版本立项。

## 十三、5.3：把控件也换成 Fluent

5.2 的界面是“Fluent 外壳 + 5.0 QSS 内页”的混合体。5.3 的目标是把控件层也换掉，同时修复用户报告的一个主题问题：切到深色后，侧边栏仍然发白。

### 13.1 深色侧栏：动画和 Mica 叠在一起

排查发现 `FluentWindow` 继承 `BackgroundAnimationWidget`。主题切换时，`backgroundColorAni` 会用 120ms 把背景从旧色过渡到新色；真实 Windows 上又启用了 Mica，`_normalBackgroundColor()` 返回透明色，导航和标题栏在动画期间就露出白底。

修复分三步：

1. `setTheme` / `setThemeColor` 后立即 `backgroundColorAni.stop()`；
2. 关闭 Mica，直接设置纯色背景（暗 `#202020`、亮 `#F0F4F9`）；
3. 把导航滚动区设为透明，再 `repaint()` 导航和标题栏。

这样切换是同步的，不再依赖动画结束。离屏截图和真实窗口的像素验证都确认导航立即变深。

### 13.2 兼容层，而不是重写 13 个页面

页面和对话框里有 100 多处 `QLineEdit` / `QComboBox` / `QDateEdit` / `QTableWidget`。逐页重写风险太高，所以新增 `ui/fluent_controls.py` 做薄兼容层：

- `LineEdit` 接受 `(text, parent)`；
- `ComboBox` 包装 qfluentwidgets `ComboBox`，兼容原有 `addItem(text, data)` / `addItem(icon, text, data)`；
- `DateEdit` 包装 `DatePicker`，兼容 `setDate` / `getDate` / `dateChanged` / `setCalendarPopup` / `setDisplayFormat`；
- `TableWidget` 包装 Fluent 表格，保留行列构造；
- `CheckBox`、`PushButton`、`PrimaryPushButton`、`SpinBox`、`ListWidget` 直接转出。

然后批量替换 import，保留页面业务代码不变。`widgets.py` 的卡片、页面、标题、搜索框、按钮、图标按钮、分段控件也改用 Fluent 组件。图表继续自绘，因为 qfluentwidgets 免费版没有等价图表控件。

### 13.3 两个 API 坑

**DatePicker 的 `date` 是属性，不是方法。** 旧代码大量调用 `.date()`，替换后报 `QDate object is not callable`；批量改成 `.getDate()`。

**`setDisplayFormat()` 会重置 DatePicker 的日期。** 报表区间一开始显示 `year / month / day` 占位符，宽度加到 300 也没用；原因是构造后再调 `setDisplayFormat`，内部 `setDateFormat` 把日期清空了。修复是保存当前日期、设置格式、再 `setDate()` 恢复。交易对话框因为后续会重新 `setDate`，所以没有暴露。

### 13.4 结果

- 13 个页面、29 个对话框全部用 Fluent 控件构造；
- 暗色/亮色切换同步生效，侧边栏不再发白；
- 173 个测试通过；
- 页面级 QSS 仅保留卡片、排版和图表调色板，通用输入控件交给 Fluent 自绘。

`QInputDialog` 也换成了 `ui/dialogs/prompt.py` 的 `TextPromptDialog`，用于模板命名和报表区间预设命名；系统文件选择器仍保留原生对话框。

这一轮也说明：Fluent 化最难的不是“换按钮”，而是 Qt 控件 API 与 Fluent 控件的语义差异。兼容层比全量重写更适合这种已有大量业务代码的项目。

## 十四、5.3.1：行情不只是 A 股

5.3 发布后，用户反馈“有些股票或者 ETF 的行情无法校准”。检查真实持仓后发现，A 股 600028、601988 可以更新，但 SCHD、VYM、INTC、QNDX、IQQ、TRON 这些美股/ETF 全部被跳过。

原因不在腾讯接口，而在本地过滤：

```python
if item.quantity_units > 0 and item.currency == "CNY"
```

`quote_symbols()` 只收集 CNY 持仓，`apply_market_quotes()` 又只写 CNY 持仓；`Quote.currency` 还固定是 CNY。可腾讯接口其实支持 `usSCHD`、`usINTC`、`usTRON`，返回体里也带 `USD`。

修复分四层：

1. `normalize_symbol()` 支持裸美股代码（`SCHD`）、前后缀（`US.SCHD`、`SCHD.US`）、A 股后缀（`600000.SH`、`510300.SS`）、港股 3–5 位补零（`700`、`0700.HK` → `hk00700`）。
2. `parse_quotes()` 从返回字段读取 `CNY/USD/HKD`，不再硬编码；时间同时兼容 `20261109160001` 和 `2026-11-09 16:00:01`。
3. `quote_symbols()` 收集 `QUOTE_CURRENCIES` 内的持仓，`apply_market_quotes()` 只在报价币种与持仓币种一致时写入，避免把 USD 价格写进 CNY 持仓。
4. 行情 UI 的刷新计数、缓存和持仓价同步沿用原链路，持仓表按账户币种显示 `$` / `HK$` / `¥`。

验证时直接复制用户数据库，保留原文件不动：8 个代码全部返回，SCHD 3565、TRON 145、INTC 5937、VYM 16272，两个 SCHD 账户同步更新；CNY 的 600028/601988 保持 569/696。测试增加到 175 个，新增美股响应解析和币种不匹配保护。

这一轮的关键教训是：**“行情不可用”有时不是网络问题，而是查询范围被业务代码悄悄缩小了。** 先打印 `quote_symbols()`，比反复换接口更快。

## 十五、5.4：把修复正式发出去

5.3.1 只在本地验证过，5.4.0 是第一个包含多市场行情修复的正式 Release。

这一版没有新增 schema，也没有继续扩大功能面，只做三件事：

1. 把版本号统一到 5.4.0，避免“代码是 5.3.1、发布包是 5.3.0”的错位；
2. 重新构建 Windows 包，确认解压后的 exe 能启动、能读取旧库；
3. 把 A/港/美行情修复、深色主题和全量 Fluent 控件一起作为正式资产发布。

对用户来说，最重要的变化不是版本号，而是“点更新行情，所有市场都能更新”。对项目来说，这也是一次发布纪律的修正：**本地验证通过的修复，只有进入正式包和 Release，才算真正交付。**

## 十六、5.4.1：全部卖出不能把持仓写成 0

5.4 发布后，用户卖出整笔持仓时报：

```text
sqlite3.IntegrityError: CHECK constraint failed: quantity_units > 0
```

堆栈落在 `record_investment_trade()` → `_write_holding_values()`。原因很直接：`holdings` 表的 `quantity_units` 从 V7 起就有 `CHECK (quantity_units > 0)`，而全部卖出时 `new_qty = old_qty - quantity_units = 0`，UPDATE 被约束拒绝。部分卖出不会触发，所以之前的 FIFO 测试没覆盖到。

修复有两种选择：

- 卖光后删除 holding，简单，但会丢掉 `realized_profit`、`dividends` 和成本信息；
- 允许持仓数量为 0，保留一行“已清仓”记录。

选择第二种。schema 升到 19，在 `SCHEMA_V19` 里重建 `holdings` 表：

1. 新建 `holdings_new`，把 `quantity_units` 约束改成 `>= 0`；
2. 原样复制 id、成本、价格、已实现收益、分红、资产类别、地区；
3. 删除旧表并重命名，重建 `idx_holdings_account`。

这样全部卖出后，holding 行保留，数量为 0、成本价为 0、已实现收益和分红不丢；再买入同一代码时会在原行上累加。`holdings_summary()` 的持仓数量也改为只统计 `quantity_units > 0` 的开放持仓。

新增测试覆盖完整链路：买入 1 份、全部卖出、断言数量 0 且已实现收益正确，再买回 0.5 份并确认成本价和收益保留。测试总数 176，全量通过。

这个 bug 的教训是：**部分卖出测试通过，不代表全部卖出成立。** 边界值（0、满仓、超卖）要单独写用例。

## 十七、结语

这次重构证明：对一个已经稳定的桌面应用，**只换壳**是可行的，而且成本远低于重写。真正花时间的不是 `FluentWindow` 本身，而是那些“壳和页面之间”的胶水：导航状态、主题同步、语言刷新、托盘关闭、打包资源；而 5.1 的四项功能说明，壳稳定之后，真正难的是数据迁移和金额口径。

如果后续继续深化，建议把图表容器、系统原生文件对话框和自定义弹窗也逐步统一，每一步都保留 175 个测试作为回归底线。

---

*本文对应的代码在 `FluentRebuild/`；5.4.0 已发布到 [GitHub Releases](https://github.com/Urtaome0211/FinBoard/releases/tag/v5.4)，5.4.1 是本地卖出修复版。*
