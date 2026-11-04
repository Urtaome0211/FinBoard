# FinBoard Fluent · 财观

FinBoard Fluent 是 [FinBoard](https://github.com/Urtaome0211/FinBoard) 5.0 的桌面界面重构版：业务层、数据层和数据库保持不变，主窗口、导航、标题栏、提示条使用 **PySide6-Fluent-Widgets** 重新搭建，视觉上更接近 Windows 11 的原生应用。

- 版本：**5.0.0**
- 技术栈：Python 3.10+、PySide6 6.6+、PySide6-Fluent-Widgets 1.11.3
- 平台：Windows 10/11（macOS/Linux 可运行源码，但未做安装包验证）
- 数据：与 FinBoard 5.0 **共用同一个 SQLite 数据库**（schema 15）
- 许可：MIT

> 本仓库是本地重构交付，**没有上传到 GitHub**，也没有创建远程仓库或 Release。

![总览](docs/screenshots/dashboard.png)

## 界面预览

| 暗色主题 | 英文界面 |
| --- | --- |
| ![暗色](docs/screenshots/dashboard-dark.png) | ![英文](docs/screenshots/dashboard-en.png) |

| 负债 | 储蓄 |
| --- | --- |
| ![负债](docs/screenshots/debts.png) | ![储蓄](docs/screenshots/savings.png) |

| 报表 | 设置 |
| --- | --- |
| ![报表](docs/screenshots/reports.png) | ![设置](docs/screenshots/settings.png) |

## 为什么做这个重构

FinBoard 5.0 的功能已经完整，但界面还是自绘 QSS 风格：导航是自绘侧栏，标题栏和窗口控制也是自定义的。Fluent 重构只替换“壳”和交互层：

- 用 `FluentWindow` + `NavigationInterface` 替换自绘侧栏，保留 13 个页面和全部快捷键。
- 标题栏嵌入 Fluent 搜索框、主按钮、币种按钮和主题按钮。
- 用 `InfoBar` 替换原有的 toast 提示。
- 保留托盘、提醒、主题、语言、撤销、退款、复制上一笔等行为。
- 页面内部的卡片和图表继续复用 5.0 的 `Page` / `Card` / 图表控件，避免重写业务逻辑带来的回归。

这样做的代价是页面内部的按钮/输入框仍是 5.0 的 QSS 控件，而不是全部换成 qfluentwidgets 控件；收益是 5.0 的 132 个测试原样通过，功能对齐成本最低。详细取舍见 [BLOG.md](BLOG.md)。

## 功能

与 FinBoard 5.0 对齐：

- **总览**：净资产、本月收入/支出/结余、资产负债环图、近 6 个月收支趋势、净资产趋势、投资浮盈、最近记录、预算进度。
- **收支明细**：筛选、搜索、标签、拆分、附件、批量编辑、撤销（Ctrl+Z）、退款关联、CSV 导出。
- **账户**：现金/储蓄/投资/信用卡/贷款，多币种，归档；系统自动创建的定期存款账户受保护。
- **负债**：贷款等额本息/等额本金摊还表、剩余本金、信用卡账单周期/最低还款、雪球/雪崩清偿计划。
- **固定资产**：估值历史、当前价值、折旧/处置之外的 5.0 既有能力。
- **预算**：月度预算、分类预算、结转、超支提醒。
- **储蓄**：定期存款、共享虚拟存款账户、到期提醒/一键支取、提前支取按活期利率、利息记收入、储蓄目标。
- **计划**：一次性计划收支，确认后入账，并进入现金流预测。
- **往来款**：应收/应付、到期/逾期、结清只改状态，不污染收支报表。
- **预测**：基于近 3 个月和定期/计划交易的现金流预测。
- **定期**：定期交易模板，确认后入账。
- **报表**：月度报表、资产负债、支出构成、标签支出、支出热力日历、固定支出体检、Excel/PDF 导出。
- **设置**：语言、主题、提醒、托盘、货币、分类、自动分类规则、数据目录、CSV 导入/导出、数据库备份/恢复/完整性检查。
- **效率**：Ctrl+N 记一笔、Ctrl+Shift+N 复制上一笔、Ctrl+F 搜索、Ctrl+Z 撤销、Ctrl+1…9 切页、托盘快速记账、记住上次账户/分类。
- **投资**：持仓、成本/市值/浮盈、资产类别/地区、配置环图、XIRR。
- **导入**：支付宝/微信/银行 CSV 预设 + 自定义列映射。
- **双语**：中文/英文，导航和页面同步切换；切换时重建主窗口，保留当前页面、窗口位置和最大化状态。

## 快速开始

### 源码运行

```bash
cd FluentRebuild
python -m pip install -r requirements.txt
python run.py
```

常用参数：

```bash
python run.py --demo                 # 使用演示数据库
python run.py --reset-demo           # 重建演示数据库
python run.py --db D:\data\my.db     # 指定数据库
python run.py --language en          # 英文界面
python run.py --theme dark           # 暗色主题
python run.py --smoke-test           # 启动后自动退出（CI/冒烟）
python run.py --version
```

### Windows 包

已构建的包位于：

```text
build/FinBoardFluent-5.0.0-win64.zip
```

解压后运行：

```text
FinBoardFluent/FinBoardFluent.exe
```

包是 one-dir 形式，必须保留同目录的 `_internal/`。

大小：90,843,377 字节（约 86.6 MiB）

SHA256：`f9d787be8306831fec8243b11c22d169b62029cd99539dd8cfa27fed7716553b`

## 数据与兼容性

FinBoard Fluent 默认复用 FinBoard 的数据目录和数据库：

```text
%LOCALAPPDATA%\FinBoard\finboard.db
%LOCALAPPDATA%\FinBoard\backups\
%LOCALAPPDATA%\FinBoard\attachments\
%LOCALAPPDATA%\FinBoard\finboard.log
```

也支持环境变量：

- `FINBOARD_DATA_DIR`：覆盖数据目录
- `FINBOARD_DB`：覆盖数据库路径

数据库 schema 为 **15**，与 FinBoard 5.0 相同。两个应用可以打开同一个数据库，但建议不要同时运行；切换前先在设置页做一次备份。第一次用 Fluent 打开 5.0 数据库不会迁移结构；如果数据库来自 4.3 或更早版本，会按原有迁移链升级到 15。

## 测试

```bash
cd FluentRebuild
QT_QPA_PLATFORM=offscreen python -m unittest discover -s tests -v
```

- 135 个测试：5.0 原有的 132 个业务/UI 测试 + 3 个 Fluent 壳测试。
- Fluent 壳测试覆盖 13 个页面、导航切换、语言切换、主题切换。
- 另有离屏截图和 11 个对话框的构造冒烟（见 `build/`，不属于测试套件）。

## 构建

```bash
cd FluentRebuild
python -m pip install -r requirements.txt
python -m PyInstaller FinBoardFluent.spec --noconfirm --clean
```

产物：

```text
dist/FinBoardFluent/FinBoardFluent.exe
dist/FinBoardFluent/_internal/
```

打包时需要 `qfluentwidgets` 的运行时数据；`FinBoardFluent.spec` 已包含：

- `finboard_fluent/resources`、`finboard_fluent/locales/en.json`
- `collect_data_files("qfluentwidgets")`
- `collect_submodules("qfluentwidgets")`
- `qframelesswindow`、`darkdetect`、`PySide6.QtSvg`、`openpyxl`

## 目录结构

```text
FluentRebuild/
├─ finboard_fluent/          # 独立包名，避免和 5.0 的 finboard 冲突
│  ├─ app.py                 # 启动参数、数据库、主题/语言
│  ├─ core/                  # 业务层（与 5.0 同源）
│  ├─ ui/
│  │  ├─ main_window.py      # FluentWindow 壳、导航、标题栏、托盘
│  │  ├─ pages/              # 13 个页面（复用 5.0 布局）
│  │  ├─ dialogs/            # 对话框（仍为 QDialog + QSS）
│  │  ├─ charts.py           # QPainter 图表
│  │  └─ theme.py            # 5.0 调色板 + QSS
│  ├─ locales/en.json
│  └─ resources/
├─ tests/                    # 135 个测试
├─ docs/screenshots/         # README 截图
├─ run.py                    # 源码启动器
├─ FinBoardFluent.spec       # PyInstaller 定义
├─ requirements.txt
├─ README.md                 # 本文件
├─ BLOG.md                   # 中文技术复盘
└─ README_original.md        # 5.0 原始 README，保留对照
```

## 已知限制

- 页面内部仍使用 5.0 的 QSS 控件；Fluent 化的是主壳、导航、标题栏、提示条。
- 对话框仍为 `QDialog` + QSS，没有换成 `qfluentwidgets.Dialog`；功能完整，视觉接近但不是 100% Fluent。
- Mica 仅在真实 Windows 且非离屏模式启用；Windows 10 或远程桌面下为纯色背景。
- 没有代码签名，Windows SmartScreen 可能提示“未知发布者”。
- 与 5.0 共用数据目录、设置和备份；两版同时运行可能互相覆盖托盘/主题/语言设置。
- 继承 5.0 的限制：无云同步/账号体系、定期交易不后台自动入账、行情手动、投资尚无逐笔买卖 lots、报表无任意区间/同比/年度报告、无自定义模板/全局迷你输入窗。

## 致谢与许可

- 原项目：FinBoard（财观），作者 Urtaome0211，MIT License。
- Fluent 组件：[PySide6-Fluent-Widgets](https://github.com/zhiyiYo/PyQt-Fluent-Widgets)（MIT）。
- 本重构仅用于本地交付与学习，不包含原项目的个人数据、备份或构建产物。
