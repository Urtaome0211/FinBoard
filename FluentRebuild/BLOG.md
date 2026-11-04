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
5. **不上传 GitHub**：本地交付，不 commit、不 push、不建 Release。

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

合计 **135 tests OK**。

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
dist/FinBoardFluent/FinBoardFluent.exe --version  → finboard-fluent 5.0.0
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
- 135 个测试通过；
- Windows one-dir 包可运行。

没有做：

- 页面内部控件的全面 Fluent 化；
- 对话框换成 `qfluentwidgets.Dialog`；
- 逐笔投资 lots、自动行情、报表任意区间/同比/年度报告；
- 自定义模板、全局迷你输入窗。

这些不是“忘了”，而是刻意把范围收在“壳层重构 + 功能对齐”。如果继续做，下一步应该优先把对话框统一成 Fluent `Dialog`，再把页面里的 `QPushButton/QLineEdit/QComboBox` 替换成 qfluentwidgets 对应控件——这会是一次更大的视觉改造，测试也要相应调整。

## 十、经验

1. **先锁依赖版本**。qfluentwidgets 迭代快，标题栏内部结构、构造参数都可能变；锁 1.11.3，升级时单独做兼容测试。
2. **壳层重构要保留页面契约**。页面只依赖 `Page` 和 `window`，换外壳时几乎不用改页面。
3. **主题要双写**。旧 QSS 和 Fluent 主题是两套系统，必须同时更新；只改一边会出现“壳变了、图表还是旧配色”。
4. **离屏截图要关 Mica**。Windows 上默认开启，透明合成在离屏环境不可靠。
5. **导航是状态机**。`switchTo`、`setCurrentItem`、`current_key` 三处要同步，否则快捷键和搜索会串页。
6. **测试迁移是最便宜的回归保险**。132 个测试原样通过，比重新点一遍页面更可靠。

## 十一、结语

这次重构证明：对一个已经稳定的桌面应用，**只换壳**是可行的，而且成本远低于重写。真正花时间的不是 `FluentWindow` 本身，而是那些“壳和页面之间”的胶水：导航状态、主题同步、语言刷新、托盘关闭、打包资源。

如果后续要继续 Fluent 化，建议按“对话框 → 表单控件 → 图表容器”的顺序推进，每步都保留 135 个测试作为回归底线。

---

*本文对应的代码在 `FluentRebuild/`，版本 5.0.0；未上传 GitHub。*
