# FinBoard · 财观

> 一个专注本地数据、界面清爽的个人财务管理桌面应用。  
> A local-first personal finance desktop app with a clean, flat interface.

[中文](#中文) · [English](#english) · [MIT License](LICENSE)

<img src="docs/screenshots/dashboard-light.png" width="880" alt="FinBoard 总览 / Dashboard">

---

## 中文

### 简介

FinBoard（财观）是一个用 **Python + PySide6（Qt 6）+ SQLite** 编写的个人财务管理软件。它把账户、收支、预算和报表放在一个桌面窗口里，所有账目只保存在本机。除每日从 Frankfurter 获取一次公开汇率外，程序不联网、不上传、不需要注册账号。

界面采用扁平化设计，提供浅色与深色两套主题；资产与负债的比例用自绘环形图展示，收支趋势、分类排行也全部由 `QPainter` 绘制，不依赖任何第三方图表库。

### 功能

- **总览**：净资产、本月收入/支出/结余、资产与负债百分比环图、近 6 个月趋势、最近记录、预算进度。
- **收支明细**：按月份、类型、账户、分类、标签筛选，支持关键词搜索；每笔显示对应账户动账后的余额（转账显示转出账户余额）；双击编辑、右键删除、Delete 删除；支持拆分、标签、附件与 CSV 导出；多选后批量改分类/加移除标签；可用 Ctrl+Z 撤销上一步操作（新增、编辑、删除、标签/拆分修改与批量修改）。
- **退款**：收入可勾选「这是一笔退款」并关联原支出；退款不计入收入，按净额冲减支出统计、分类排行与现金流预测；系统会校验原支出类型、退款上限和删除顺序。
- **账户**：现金、储蓄卡、投资理财、信用卡、贷款五类账户；每个账户可设自己的币种；实时余额由期初余额和流水聚合得出；信用卡/贷款按欠款金额（正数）录入，自动计入负债；支持归档与恢复。
- **固定资产**：登记房产、车辆等长期资产，记录购买价、当前估值和估值日期；计入总资产/净资产与结构环图，不计入可用现金、预算和现金流预测。
- **投资市值**：投资理财账户可按日记录收盘总市值，账户余额自动变为「最新市值 + 市值日之后的流水」；带历史曲线、同日覆盖、删除重算，市值变动不计入收支。
- **多币种**：账户级 + 交易级币种；按每个交易日的汇率折算后汇总，周末和节假日沿用最近一个工作日；基准币种可切换，总览/报表/预算统一按基准币种显示。
- **钱包提现手续费**：从「支付宝钱包」或「微信钱包」转出时，按 0.1% 自动扣手续费（支付宝最低 ¥0.10，微信最低 ¥0.01）；全部提现时手续费包含在提现金额中，部分提现时从剩余余额另扣；可勾选「本次豁免手续费」。手续费计入支出统计，报表中归入「提现手续费」。
- **定期交易**：把房租、工资、会员费等设为每日/每周/每月/每年重复；到期后在「定期」页确认入账，可单笔或全部入账，规则可暂停、编辑、删除。
- **账户对账**：输入银行或钱包显示的账单余额，程序计算差额并写入账户校准；不会生成收支记录，可删除对账历史撤销调整；投资账户请使用市值快照。
- **投资持仓与现金**：为投资账户登记股票、基金或 ETF 的数量、成本价和现价，自动计算成本、市值、浮动盈亏与收益率；持仓之外可单独填写现金，账户总值 = 现金 + 持仓市值，可一键按总值校准账户；已实现收益、累计分红计入累计收益。
- **预算结转**：勾选「结转到下月」后，本月未用完的正预算会带入下月；超支不结转，明细页显示结转额与可用预算。
- **储蓄目标**：为目标设定金额、已存金额和可选日期，显示进度、剩余与达成状态，支持随时存入或取出。
- **现金流预测**：按定期交易和最近 3 个月的非定期收支，预测未来 3/6/12 个月的收入、支出、净现金流和期末现金。
- **汇率**：每日自动检查一次，也可在设置页手动刷新；数据来自 Frankfurter（欧洲央行参考汇率），缓存在本地，离线时继续使用最后一次汇率。
- **预算**：按月设置总预算和分类预算，实时显示已用、剩余、使用率；超支时用红色提示；可开启跨月结转。
- **报表**：投资组合汇总、资产/负债结构、本月支出构成、近 12 个月趋势、支出分类排行、消费对象 Top 5；可导出 Excel 或 PDF。
- **记账**：支持支出、收入、账户间转账；可填写日期、金额、账户、分类、对方、备注。
- **分类管理**：自定义支出/收入分类名称与颜色；删除分类时，历史记录自动归入「其他」。
- **自动分类规则**：按付款对象关键词自动填充分类与标签；可在设置页管理规则、从历史记录学习（同一付款对象至少出现两次且分类一致），并把规则标签回填到历史交易。
- **数据**：CSV 导入/导出（支持自定义列映射、保存导入规则、按日期/类型/金额/账户/对方去重）、数据库备份（启动时完整性检查、每日自动轮转、可从备份恢复）、载入演示数据、清空全部数据。
- **交易元数据**：一笔支出/收入可拆分到多个分类（合计必须等于交易金额），可加多个标签，可把回单/发票复制为附件；转账不可拆分。
- **体验**：浅色/深色主题一键切换、中英文界面切换（默认中文）、全局搜索、快捷键、卡片式扁平布局。

### 界面

| 总览（浅色） | 总览（深色） |
| --- | --- |
| ![总览浅色](docs/screenshots/dashboard-light.png) | ![总览深色](docs/screenshots/dashboard-dark.png) |

| 收支明细 | 账户 |
| --- | --- |
| ![收支明细](docs/screenshots/transactions.png) | ![账户](docs/screenshots/accounts.png) |

| 固定资产 | 报表 |
| --- | --- |
| ![固定资产](docs/screenshots/fixed-assets.png) | ![报表](docs/screenshots/reports.png) |

| 批量编辑 | 批量修改对话框 |
| --- | --- |
| ![批量编辑](docs/screenshots/bulk-edit.png) | ![批量修改](docs/screenshots/bulk-dialog.png) |

| 多币种明细 | 汇率与设置 |
| --- | --- |
| ![多币种明细](docs/screenshots/multicurrency.png) | ![设置](docs/screenshots/settings.png) |

| 投资账户 | 市值记录 |
| --- | --- |
| ![投资账户](docs/screenshots/accounts-investment.png) | ![市值记录](docs/screenshots/valuation.png) |

| 定期交易 | 账户对账 |
| --- | --- |
| ![定期交易](docs/screenshots/recurring.png) | ![账户对账](docs/screenshots/reconcile.png) |

| 投资持仓 | 储蓄目标 |
| --- | --- |
| ![投资持仓](docs/screenshots/holdings.png) | ![储蓄目标](docs/screenshots/savings.png) |

| 现金流预测 | 英文总览 |
| --- | --- |
| ![现金流预测](docs/screenshots/forecast.png) | ![英文总览](docs/screenshots/dashboard-en.png) |

| CSV 导入映射 | 拆分、标签与附件 |
| --- | --- |
| ![CSV 导入](docs/screenshots/csv-import.png) | ![交易元数据](docs/screenshots/metadata.png) |

| PDF 报表预览 |  |
| --- | --- |
| ![PDF 报表](docs/screenshots/report-pdf.png) |  |

| English overview | English settings |
| --- | --- |
| ![English overview](docs/screenshots/dashboard-en.png) | ![English settings](docs/screenshots/settings-en.png) |

更多截图在 [`docs/screenshots/`](docs/screenshots/)。

### 技术栈

| 层 | 选择 |
| --- | --- |
| 语言 | Python 3.10+ |
| GUI | PySide6 6.6+ / Qt 6 Widgets |
| 数据库 | SQLite（标准库 `sqlite3`） |
| 导出 | openpyxl（Excel）；Qt `QPdfWriter`（PDF） |
| 汇率 | Frankfurter（ECB 参考汇率）+ 本地缓存 |
| 图表 | 纯 `QPainter` 自绘（环图、折线图、条形图） |
| 样式 | QSS + `QPalette`，双主题 |
| 图标 | 内联 SVG，运行时着色 |
| 打包 | PyInstaller（Windows one-dir） |

运行时依赖 PySide6 和 openpyxl（用于 Excel 导出）。Pillow 只用于生成应用图标，PyInstaller 只用于构建 exe，二者都不是运行依赖。PDF 由 Qt 自带的 `QPdfWriter` 生成，汇率请求使用标准库 `urllib`，没有额外的网络库。

### 快速开始

#### 1. 源码运行

```bash
git clone <this-repo> FinBoard
cd FinBoard

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

也可以：

```bash
python run.py --demo          # 使用独立的演示数据库
python run.py --reset-demo    # 重建演示数据并打开
python run.py --db D:\data\my.db
python run.py --theme dark
python run.py --language en
python -m finboard --version
```

首次启动会自动建库、写入默认分类和一个「现金」账户。若想直接看到完整效果，推荐运行 `python run.py --reset-demo`。

#### 2. 直接运行 exe

构建后的可执行文件位于：

```text
dist/FinBoard/FinBoard.exe
```

双击即可运行；整个 `dist/FinBoard/` 文件夹一起分发。也可以带参数：

```bat
dist\FinBoard\FinBoard.exe --demo
dist\FinBoard\FinBoard.exe --db D:\data\my.db
dist\FinBoard\FinBoard.exe --language en
dist\FinBoard\FinBoard.exe --version
```

### 使用说明

1. **先更新汇率**：在「设置 → 汇率」点一次「更新汇率」。程序每天首次启动时会自动检查一次；外币账户、外币交易和基准币种切换都需要至少一次成功更新。
2. **建账户**：在「账户」页新建现金、银行卡、信用卡或贷款账户，选择账户币种，填入期初余额。信用卡、贷款请填写**欠款金额（正数）**，程序会自动转为负余额并计入负债；编辑旧账户保存时也会自动转换。账户一旦有流水，币种不可再改。
3. **记录投资市值**：投资理财账户行的折线图标打开「市值记录」。填入某个交易日的**收盘总市值**（账户币种），保存后余额 = 最新市值 + 该日期之后的收入/支出/转账净额；同日再次保存会覆盖。历史曲线和记录列表里可以删除旧快照，余额会立即重算。市值变化只影响账户余额和净资产，不计入当月收入或支出。
4. **记一笔**：点右上角「记一笔」或按 `Ctrl+N`，选择支出/收入/转账，填写金额、币种、账户和分类。交易币种可以和账户币种不同，程序按交易日期汇率折算入账，并在下方显示折算预览。转账会让转出账户减少、转入账户增加；跨币种转账可自动或手动填写「到账金额」。
   - 如果转出账户是「支付宝钱包」或「微信钱包」（也识别「支付宝」「微信」），程序会自动按提现金额的 0.1% 扣手续费：支付宝每笔最低 ¥0.10，微信每笔最低 ¥0.01。**全部提现**时源账户只扣填写的金额，手续费包含在其中，转入账户收到扣费后的净额；**部分提现**时源账户扣「提现金额 + 手续费」，转入账户收到填写的金额。勾选「本次豁免手续费」可跳过本次费用。手续费计入当月支出，但不会生成一条独立流水。
   - 规则按**账户名称**识别，仅对人民币钱包生效；改名后不再自动计费。全部提现按「提现金额恰好等于源账户当前可用余额」自动判定。
5. **设定期交易**：在「定期」页新建规则，选择频率（每天/每周/每月/每年）、间隔、开始日期和可选的结束日期。到期规则会出现在页面顶部，确认后才写入收支；也可以点「全部入账」一次处理所有到期规则。规则不会在后台自动记账。
6. **账户对账**：在账户行点勾选图标，输入银行/钱包显示的余额和日期。差额会作为校准写入该账户，不生成收支、不影响预算；可在「最近对账」里删除记录撤销校准。投资账户请用市值记录校准。
7. **设预算**：在「预算」页选择月份，先设置本月总预算，再给重点分类单独设上限。预算金额使用当前基准币种。
8. **看报表**：在「报表」页切换月份，查看资产/负债比例、支出结构和趋势；所有汇总按交易日汇率折算为基准币种。
9. **备份数据**：在「设置 → 数据」中备份数据库或导出 CSV。CSV 也可用于从其他软件迁移数据。
10. **切换语言**：在「设置 → 语言」选择「中文」或「English」，切换立即生效并记住选择；默认中文。也可以在启动时用 `--language en` 临时指定。
11. **登记持仓与现金**：在投资账户行点「持仓」图标，添加名称、代码、数量、成本价和现价；点「调整现金」填写未投入持仓的现金，账户总值会按「现金 + 持仓市值」显示；点「按市值校准账户」把账户总值写成当天的市值快照。
12. **设储蓄目标**：在「储蓄」页新建目标，填写目标金额、已存金额和可选日期；在目标行点「+」存入，点铅笔编辑，点垃圾桶删除。
13. **看现金流预测**：在「预测」页选择未来 3/6/12 个月，查看预测曲线和逐月表；期初现金只算现金/储蓄卡账户，定期收支按计划日期投影，转账不计入。
14. **登记固定资产**：在「固定资产」页新增房产、车辆或其他长期资产，填写购买价、当前估值和估值日期；估值只影响总资产/净资产与结构环图，不生成收支、不进入预算和现金流预测。

快捷键：

| 快捷键 | 动作 |
| --- | --- |
| `Ctrl+N` | 记一笔 |
| `Ctrl+F` | 全局搜索 |
| `Ctrl+,` | 设置 |
| `Ctrl+1` … `Ctrl+9` | 总览 / 收支明细 / 账户 / 固定资产 / 预算 / 储蓄 / 预测 / 定期 / 报表 |
| `Delete` | 删除选中的收支记录 |

### CSV 格式

导出文件使用 UTF-8（带 BOM），导入兼容 UTF-8 与 GB18030。表头固定为：

```csv
日期,类型,金额,币种,分类,账户,转入账户,到账金额,对方,备注
2026-10-01,支出,35.50,CNY,餐饮,微信钱包,,,瑞幸咖啡,早餐
2026-10-05,收入,18500.00,CNY,工资,招商银行储蓄卡,,,公司,10 月工资
2026-10-06,转账,1000.00,CNY,,人民币储蓄卡,美元储蓄卡,150.00,,购汇
2026-10-07,支出,12.00,USD,餐饮,美元储蓄卡,,,Amazon,美元消费
```

说明：

- 金额为**正数**，最多两位小数，不需要货币符号；`币种` 留空时按 `CNY` 处理。
- `类型` 可取 `支出`、`收入`、`转账`。
- 支出/收入必须填写分类；转账必须填写转入账户，分类留空。
- `到账金额` 只用于跨币种转账；留空时按交易日期汇率自动折算。外币交易和跨币种转账需要本地已有对应日期的汇率。
- 手续费是派生值，不单独占 CSV 列；导入钱包转账时按账户名、金额和日期重新计算。
- 导入前请先建好同名、同币种的账户和分类；无法识别的行会被跳过，并在结果中给出原因。
- 上面的表头是 FinBoard 自己的导出格式。导入外部 CSV 时可在「导入 CSV」对话框里把任意列映射到日期、类型、金额、账户等字段，并保存为规则；勾选去重后会跳过重复导入的行。

### 数据与隐私

默认数据目录：

```text
%LOCALAPPDATA%\FinBoard\
├── finboard.db        # 主数据库
├── finboard-demo.db   # --demo 使用的演示数据库
└── finboard.log       # 运行日志
```

- 可用环境变量 `FINBOARD_DATA_DIR` 改数据目录，或用 `FINBOARD_DB` 指定数据库文件。
- 若用户目录不可写（便携盘、受限环境），程序会自动回退到可执行文件旁的 `FinBoard-Data\finboard.db`，并在启动时提示。
- 账目全部保存在本地 SQLite 文件中。程序唯一的网络请求是向 Frankfurter 获取公开汇率；请求只包含目标币种列表，不包含任何账户、金额或个人信息。离线时继续使用本地缓存汇率。
- 备份方式：设置页「备份数据库」或「从备份恢复」；程序启动时会做完整性检查，并把超过 20 小时的备份自动写入 `backups/`。也可直接复制 `finboard.db`（建议先退出程序）。

### 项目结构

```text
finboard/
├── app.py                  # QApplication、参数、设置、数据库生命周期
├── i18n.py                 # 运行时翻译、语言状态与本地化格式
├── locales/en.json         # 英文词典（含动态模板）
├── core/
│   ├── money.py            # 整数分金额解析/格式化
│   ├── dates.py            # 月份与日期工具
│   ├── models.py           # dataclass 模型与常量
│   ├── database.py         # schema、迁移、默认数据
│   ├── repository.py       # SQL 查询、写入与多币种折算
│   ├── rates.py            # 汇率缓存、每日抓取与换算
│   ├── fees.py             # 支付宝/微信提现手续费规则
│   ├── csv_io.py           # CSV 导入/导出、列映射与去重
│   ├── exporters.py        # Excel 报表导出
│   ├── service.py          # 面向 UI 的服务层 + changed 信号
│   ├── demo.py             # 12 个月演示数据
│   └── paths.py            # 数据/资源路径（含 PyInstaller）
├── ui/
│   ├── theme.py            # 两套 Palette + QSS
│   ├── localize.py         # 翻译现有控件树与弹窗
│   ├── icons.py            # 内联 SVG 图标
│   ├── widgets.py          # Card、Badge、按钮、对话框基件
│   ├── charts.py           # 环形图、趋势图、分类条形图
│   ├── pdf_export.py       # QTextDocument/QPdfWriter 报表
│   ├── models.py           # 交易表模型、持仓表模型与类型徽章代理
│   ├── rows.py             # 交易/账户列表行
│   ├── main_window.py      # 侧栏、顶栏、页面路由
│   ├── dialogs/            # 记账、账户、市值、持仓、储蓄、分类、预算、定期、对账、CSV、元数据
│   └── pages/              # 总览、明细、账户、固定资产、预算、储蓄、预测、定期、报表、设置
├── resources/              # 图标、勾选/下拉 SVG
└── __main__.py
tests/test_core.py          # 金额/日期/仓储/CSV/服务层测试
tests/test_rates.py         # 汇率、跨币种转账与币种 CSV 测试
tests/test_fees.py          # 钱包提现手续费与统计测试
tests/test_valuations.py    # 投资市值、快照后流水与余额锁定测试
tests/test_balances.py      # 明细动账后余额、手续费、同日排序与快照边界测试
tests/test_ui.py            # 账户/交易/市值对话框、自动更新汇率测试
tests/test_i18n.py          # 中英词典、日期/金额格式与控件跳过规则
tests/test_v2.py            # 定期交易、对账、页面/对话框集成测试
tests/test_v21.py           # 持仓、预算结转、储蓄目标、现金流预测
tests/test_v21_ui.py        # 持仓/储蓄目标对话框
tests/test_v30.py           # schema v10、拆分/标签/附件、CSV 规则、Excel 导出
tests/test_v40.py           # 持仓已实现收益/分红、批量编辑与撤销
tests/test_v41.py           # 固定资产 CRUD、估值折算与净值
scripts/                    # 冒烟、截图、图标生成
docs/                       # 截图与 logo
run.py                      # 源码入口
FinBoard.spec               # PyInstaller 构建配置
```

### 关键设计

- **整数分**：数据库与内存中的金额全部是 `int` 分，只在输入/显示边界转换，避免 `0.1 + 0.2` 类浮点误差。
- **多币种折算**：汇率以 `1 CNY = rate` 存表，跨币种经 CNY 中转；每笔交易保留原币金额、账户入账额和（转账）到账额，汇总时按交易日汇率折算，历史报表不会因今天的汇率变化而漂移。
- **余额不落库**：账户余额 = 期初余额 + 收入 − 支出 ± 转账，由 SQL 聚合实时计算；避免多写一份余额导致不一致。
- **转账双账户**：转账只存一条 `transactions` 记录，查询时同时计入转出和转入账户；报表统计收支时排除转账。
- **提现手续费**：转账记录保留 `fee`、`fee_waived`、`fee_included`；钱包转出时由 `fees.py` 按账户名和折算后人民币金额计算。全部提现从金额内扣费并转出净额，部分提现从余额另扣，豁免时为 0；余额、月度统计和分类报表都会计入，CSV 导入时重新计算。
- **投资市值快照**：`account_valuations` 每个账户每日最多一条；最新快照接管余额，只叠加 `date > 快照日期` 的流水。市值变化不写入 `transactions`，因此不会伪装成收入或支出；删除快照后余额自动回到上一份快照或期初余额。
- **定期交易**：规则只保存模板和 `next_date`，到期后由用户确认才调用记账逻辑；入账后按频率推进下一次日期，月末日期会自动夹到目标月份的最后一天，超过结束日期自动停用。
- **账户对账**：账单余额与账本余额的差额写入 `accounts.adjustment`，不产生 `transactions`，所以不会污染收支、预算和分类报表；对账历史删除时会把差额撤销。
- **退款净额**：退款仍是一条 `income` 记录，但带有 `refund_of_id` 指向原支出；月度统计、趋势、分类报表和现金流预测会把退款从支出中扣减，而不会把它算作收入，从而避免收入与支出同时虚增。
- **自动分类**：`category_rules` 用 `lower(pattern) + kind` 唯一约束保存关键词，匹配时按 `casefold` 包含、最长关键词优先；新建交易时只提示并预填，命中计数与标签回填都是显式操作。
- **备份与恢复**：启动时先执行 `PRAGMA quick_check`，超过 20 小时未备份则用 SQLite 在线备份写入 `backups/`，默认保留 10 份；恢复前会先为当前数据库创建一份安全快照，并校验目标库的 schema 版本与完整性。
- **持仓与现金**：`holdings` 用百万分之一股存储数量，成本/市值/盈亏全部用整数分计算；投资账户没有市值快照时，余额 = 现金 + 持仓市值。现金通过 `accounts.adjustment` 校准，不写收支；「按市值校准」会把现金和持仓合计写成当天估值。
- **预算结转**：只有上个月开启 rollover 且剩余为正时才带入下月，逐月递归；超支归零，避免负预算继续扩张。
- **现金流预测**：期初现金只含现金/储蓄卡账户；非定期收支取近 3 个完整月均值，定期规则按 `next_date` 逐次投影；转账不计入。
- **自绘图表**：环图、折线图、分类条全部在 `paintEvent` 中绘制，颜色取当前 Palette，主题切换即时重绘。
- **主题系统**：一个 `Palette` dataclass 驱动 QPalette、QSS 与图表；设置保存在 `QSettings`。
- **本地优先**：没有账号、云同步、遥测；只有每日一次公开汇率请求，失败不影响离线使用。

### 测试与构建

```bash
# 单元测试（116 个）
python -m unittest discover -s tests

# 核心冒烟（临时数据库、演示数据、CSV 往返）
python scripts/smoke_core.py

# 界面截图（浅色 / 深色）
python scripts/smoke_ui.py
python scripts/smoke_ui.py --theme dark

# 构建 Windows exe
pip install -r requirements-dev.txt
python -m PyInstaller FinBoard.spec --noconfirm --clean
```

构建产物：`dist/FinBoard/FinBoard.exe`（one-dir，整个文件夹一起分发）。

### 已知限制

- 汇率来自 Frankfurter（ECB 参考汇率），不含周末/节假日单独报价；周末交易沿用最近一个工作日。若交易日期早于本地最早汇率，会退回到最早一条，建议外币记账前先更新汇率。
- 市值记录只对投资理财账户开放。快照按“当日收盘后的总市值”理解：快照日及之前的流水视为已包含在市值里，只有快照日之后的收支/转账才会叠加到余额。
- 基准币种切换只改变汇总显示，不会改写已有预算金额，切换后请复核预算。
- 提现手续费只对账户名为「支付宝钱包 / 微信钱包」（或「支付宝 / 微信」）的人民币账户自动计算；改名或使用其他名称不会计费。手续费规则是内置的，不随支付宝/微信官方调整自动更新。CSV 不保存「豁免 / 全部提现」标记，导入钱包转账时会按金额和账户余额重新计算，导入后请复核。
- 定期交易不会在后台自动入账，必须到「定期」页确认；这是为了避免程序未运行时错过日期却静默改账。
- 账户对账只对普通账户开放；投资账户请用市值快照校准。对账调整不写入收支，删除对账历史会撤销对应差额。
- 固定资产只记录购买价和当前估值，不做折旧、贷款关联或处置；首版也不支持附件。
- 退款只能关联支出记录，且同一原支出的退款合计不能超过原金额；退款不计收入、只冲减支出，因此报表净额与流水笔数可能不同。
- 自动分类规则按付款对象包含关键词匹配，多个规则命中时取最长关键词；规则只在新建或编辑交易时提示，不会静默改写已保存的交易，标签回填需手动触发。
- 自动备份默认开启，最多保留 10 份数据库快照，启动时超过 20 小时未备份才会创建；备份只含数据库，附件仍需另行备份 `attachments/`。
- 撤销日志最多保留最近 100 步，覆盖新增、编辑、删除、标签/拆分修改和批量修改；重启后仍可撤销，但清空数据库会一并清除。
- 单用户、单机；没有登录、加密或云同步。
- 预算按自然月设置；只有勾选「结转到下月」的预算才会把正剩余带入下月，超支不结转。
- 不直接连接银行/支付宝/微信账单，需通过 CSV 导入；自定义 CSV 规则只在导入时使用，不改变原始文件。
- 拆分、标签和附件属于本机数据；附件复制到数据目录后不加密，备份数据库时请一并备份 `attachments/`。
- CSV 去重依据日期、类型、金额、币种、账户、转入账户和对方，不包含备注；重复导入前请确认这些字段足以识别同一笔交易。
- one-dir 包没有单文件自解压步骤；请保持 `FinBoard.exe` 与 `_internal` 目录的相对位置。
- 英文界面只翻译程序文案；账户名、交易对方、备注和自定义分类名属于用户数据，会保持原样。

### 许可证

[MIT](LICENSE) © 2026 Urtaome0211

---

## English

### Overview

**FinBoard** is a personal finance desktop application built with **Python, PySide6 (Qt 6) and SQLite**. Accounts, transactions, budgets and reports live in one native window. Your books stay on your machine: no account, no cloud, no telemetry. The only network request is a daily public exchange-rate lookup from Frankfurter.

The interface is flat and calm, with light and dark themes. The asset/liability split is rendered as a custom donut chart, and all trend and category charts are drawn with `QPainter` — no third-party charting library.

### Features

- **Dashboard**: net worth, monthly income/expense/balance, asset-vs-liability donut, 6-month trend, recent transactions and budget progress.
- **Transactions**: filter by month, kind, account, category and tag; search by payee/note; each row shows the account balance after that posting (transfers show the source account); edit, delete, split across categories, tag, attach receipts and export to CSV; select multiple rows to change category or add/remove tags in bulk; press Ctrl+Z to undo the last action (new entry, edit, delete, tag/split change or bulk edit).
- **Refunds**: tick “This is a refund” on an income entry and link it to the original expense. Refunds do not count as income; they reduce expense totals, category rankings and cash-flow forecasts on a net basis. The original kind, refund cap and deletion order are validated.
- **Accounts**: cash, debit card, investment, credit card and loan accounts, each with its own currency. Balances are aggregated from the opening balance and transactions in real time. Archive and restore are supported.
- **Fixed assets**: track property, vehicles and other long-lived assets with purchase price, current value and valuation date. They count toward total assets and net worth, and appear as a separate donut segment; they are excluded from liquid cash, budgets and cash-flow forecasts.
- **Investment valuations**: record a closing market value per day for investment accounts. The balance becomes “latest snapshot + later transactions”, with a history chart, same-day overwrite and delete-to-recalculate. Market moves are not counted as income or expense.
- **Multi-currency**: account-level and transaction-level currencies. Amounts are converted at the transaction-date rate, with weekend/holiday fallback to the latest business day. The base currency can be switched; dashboard, reports and budgets are shown in it.
- **Wallet withdrawal fees**: transfers out of “支付宝钱包” or “微信钱包” automatically add a 0.1% fee (minimum ¥0.10 for Alipay, ¥0.01 for WeChat). A full withdrawal includes the fee in the withdrawn amount; a partial withdrawal deducts it from the remaining balance. Tick “Waive fee” to skip it for one transfer. Fees are counted as expenses and grouped under “提现手续费” in reports.
- **Recurring transactions**: create daily/weekly/monthly/yearly rules for rent, salary or subscriptions. Due rules appear on the Recurring page and are posted only after you confirm, individually or all at once; rules can be paused, edited or deleted.
- **Account reconciliation**: enter the statement balance from a bank or wallet; FinBoard calculates the difference and writes a balance adjustment without creating income/expense rows. Delete a reconciliation to undo it; investment accounts use valuation snapshots instead.
- **Holdings & cash**: record quantity, cost price and current price for stocks, funds or ETFs; FinBoard calculates cost basis, market value, unrealized P/L and return. Cash not invested in holdings can be entered separately, and the account total is cash plus holdings market value. A button revalues the account with that total. Realized gains and dividends are included in the total return.
- **Budget rollover**: with “Roll over to next month” enabled, unused positive budget carries into the next month; overspending does not.
- **Savings goals**: set a target, saved amount and optional date; track progress, remaining amount and completion, and deposit or withdraw at any time.
- **Cash-flow forecast**: project income, expenses, net cash flow and ending cash for the next 3/6/12 months from recurring rules and the last 3 months of non-recurring activity.
- **Rates**: one automatic check per day plus a manual refresh in Settings. Data comes from Frankfurter (ECB reference rates) and is cached locally, so offline use keeps the last known rates.
- **Budgets**: per-month overall and per-category limits, with spent/remaining/usage, over-budget warnings and optional rollover (only positive unused amounts carry).
- **Reports**: asset/liability structure, monthly expense composition, 12-month trend, portfolio summary, category ranking and top payees; export to Excel or PDF.
- **Bookkeeping**: expenses, income and account-to-account transfers with date, amount, account, category, payee and note.
- **Categories**: custom names and colors; deleting a category moves its history to “Other”.
- **Automatic category rules**: fill category and tags from a payee keyword. Manage rules in Settings, learn them from history (same payee at least twice with one category), and backfill rule tags into matching transactions.
- **Data tools**: CSV import/export with custom column mapping, saved import rules and duplicate detection (date, kind, amount, account, payee); database backup with startup integrity checks, daily rotation and restore; demo data and full reset.
- **Transaction metadata**: split an expense/income across categories (the total must equal the transaction), add multiple tags and copy receipts/invoices as attachments. Transfers cannot be split.
- **Experience**: light/dark theme, Chinese/English interface with Chinese as the default, global search, keyboard shortcuts, flat card layout.

### Screenshots

| Dashboard (light) | Dashboard (dark) |
| --- | --- |
| ![Dashboard light](docs/screenshots/dashboard-light.png) | ![Dashboard dark](docs/screenshots/dashboard-dark.png) |

| Transactions | Accounts |
| --- | --- |
| ![Transactions](docs/screenshots/transactions.png) | ![Accounts](docs/screenshots/accounts.png) |

| Fixed assets | Reports |
| --- | --- |
| ![Fixed assets](docs/screenshots/fixed-assets-en.png) | ![Reports](docs/screenshots/reports-en.png) |

| Bulk selection | Bulk edit |
| --- | --- |
| ![Bulk selection](docs/screenshots/bulk-edit.png) | ![Bulk edit](docs/screenshots/bulk-dialog.png) |

| Multi-currency transactions | Rates & settings |
| --- | --- |
| ![Multi-currency](docs/screenshots/multicurrency.png) | ![Settings](docs/screenshots/settings.png) |

| Investment accounts | Valuation history |
| --- | --- |
| ![Investment accounts](docs/screenshots/accounts-investment.png) | ![Valuation history](docs/screenshots/valuation.png) |

| Recurring transactions | Account reconciliation |
| --- | --- |
| ![Recurring](docs/screenshots/recurring-en.png) | ![Reconciliation](docs/screenshots/reconcile-en.png) |

| Holdings | Savings goals |
| --- | --- |
| ![Holdings](docs/screenshots/holdings-en.png) | ![Savings goals](docs/screenshots/savings-en.png) |

| Cash-flow forecast | Chinese overview |
| --- | --- |
| ![Cash-flow forecast](docs/screenshots/forecast-en.png) | ![Chinese overview](docs/screenshots/dashboard-light.png) |

| CSV import mapping | PDF report preview |
| --- | --- |
| ![CSV import](docs/screenshots/csv-import-en.png) | ![PDF report](docs/screenshots/report-pdf.png) |

| English dashboard | English settings |
| --- | --- |
| ![English dashboard](docs/screenshots/dashboard-en.png) | ![English settings](docs/screenshots/settings-en.png) |

![Wallet withdrawal fees](docs/screenshots/wallet-fees.png)

### Tech stack

| Layer | Choice |
| --- | --- |
| Language | Python 3.10+ |
| GUI | PySide6 6.6+ / Qt 6 Widgets |
| Storage | SQLite via the standard `sqlite3` module |
| Export | openpyxl (Excel); Qt `QPdfWriter` (PDF) |
| FX rates | Frankfurter (ECB reference rates) + local cache |
| Charts | Custom `QPainter` (donut, line, bars) |
| Styling | QSS + `QPalette`, two themes |
| Icons | Inline SVG, tinted at runtime |
| Packaging | PyInstaller (Windows one-dir) |

Runtime dependencies are PySide6 and openpyxl (Excel export). Pillow is used only to generate the app icon and PyInstaller only to build the executable. PDF is rendered by Qt's built-in `QPdfWriter`; rate requests use the standard-library `urllib`, with no extra networking package.

### Quick start

#### From source

```bash
git clone <this-repo> FinBoard
cd FinBoard

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
# source .venv/bin/activate

pip install -r requirements.txt
python run.py
```

Useful options:

```bash
python run.py --demo          # isolated demo database
python run.py --reset-demo    # rebuild demo data, then open
python run.py --db D:\data\my.db
python run.py --theme dark
python run.py --language en
python -m finboard --version
```

The first launch creates the database, default categories and a “Cash” account. For a fully populated tour, run `python run.py --reset-demo`.

#### Prebuilt executable

```text
dist/FinBoard/FinBoard.exe
```

Double-click it, or pass the same flags (ship the whole `dist/FinBoard/` folder):

```bat
dist\FinBoard\FinBoard.exe --demo
dist\FinBoard\FinBoard.exe --db D:\data\my.db
dist\FinBoard\FinBoard.exe --language en
dist\FinBoard\FinBoard.exe --version
```

### How to use

1. **Update rates first** in Settings → Rates. The app also checks once on the first launch of each day. Foreign-currency accounts, foreign-currency transactions and base-currency switches need at least one successful update.
2. **Create accounts** on the Accounts page. Pick a currency and enter an opening balance; use a **positive debt amount** for credit cards and loans — the app stores it as a negative balance and counts it as a liability. A currency cannot be changed once the account has transactions.
3. **Record investment valuations**: use the chart icon on an investment account to record that day's closing market value in the account currency. The balance becomes “latest snapshot + later transactions”; saving the same day overwrites, and deleting a snapshot recalculates. Market moves affect net worth, not income or expense.
4. **Add a transaction** with `Ctrl+N` or the “Add” button. Pick expense, income or transfer, then amount, currency, account and category. The transaction currency may differ from the account currency; the app converts at the transaction date and previews the posting. A transfer decreases the source account and increases the destination account; cross-currency transfers accept an optional destination amount.
   - If the source account is “支付宝钱包” or “微信钱包” (or simply “支付宝”/“微信”), FinBoard adds a 0.1% withdrawal fee automatically: at least ¥0.10 for Alipay and ¥0.01 for WeChat. For a **full withdrawal**, the fee is included in the amount and the destination receives the net; for a **partial withdrawal**, the source pays the amount plus the fee and the destination receives the amount entered. Tick “Waive fee” to skip the fee for this transfer. It counts as an expense but does not create a separate transaction row.
   - Fees are keyed by account name and only apply to CNY wallets; renaming the wallet disables the rule. A withdrawal is treated as “full” when its amount equals the source account's current available balance.
5. **Set up recurring transactions** on the Recurring page: pick a frequency (daily/weekly/monthly/yearly), interval, start date and an optional end date. Due rules appear in the banner and are written only after you confirm; “Post all” handles every due rule. Nothing posts in the background.
6. **Reconcile an account** with the check icon on its row: enter the statement balance and date. The difference is stored as an adjustment, not as income/expense, so budgets and reports stay clean. Delete a reconciliation in the dialog to undo it. Use valuation snapshots for investment accounts instead.
7. **Set budgets** on the Budgets page: an overall monthly limit first, then optional category limits. Budgets use the current base currency.
8. **Review reports** on the Reports page; switch months to compare. All totals are converted to the base currency at each transaction's date.
9. **Back up** from Settings → Data (database copy or CSV export).
10. **Switch language** in Settings → Language (中文 / English). The change is immediate and remembered; Chinese is the default. `--language en` overrides it for one launch.
11. **Track holdings and cash** from the chart icon on an investment account: add name, symbol, quantity, cost price and current price. Use “Adjust cash” for uninvested cash; the account total is cash plus holdings. Review cost/market value/P&L, then click “Revalue account” to write the total as today’s valuation snapshot.
12. **Set a savings goal** on the Savings page: enter a target, saved amount and optional date. Use “+” to deposit, the pencil to edit and the trash icon to delete.
13. **Review the cash-flow forecast** on the Forecast page for the next 3/6/12 months. Starting cash includes only cash/debit accounts; recurring rules project on their scheduled dates and transfers are excluded.
14. **Register fixed assets** on the Fixed assets page: name, type, purchase price, current value and valuation date. Valuations affect total assets/net worth and the structure donut only; they never create income/expense rows and are excluded from budgets and forecasts.

Shortcuts:

| Shortcut | Action |
| --- | --- |
| `Ctrl+N` | New transaction |
| `Ctrl+F` | Global search |
| `Ctrl+,` | Settings |
| `Ctrl+1` … `Ctrl+9` | Dashboard / Transactions / Accounts / Fixed assets / Budgets / Savings / Forecast / Recurring / Reports |
| `Delete` | Delete selected transaction |

### CSV format

Exports are UTF-8 with BOM; imports accept UTF-8 and GB18030. The header is fixed:

```csv
日期,类型,金额,币种,分类,账户,转入账户,到账金额,对方,备注
2026-10-01,支出,35.50,CNY,餐饮,微信钱包,,,瑞幸咖啡,早餐
2026-10-05,收入,18500.00,CNY,工资,招商银行储蓄卡,,,公司,October salary
2026-10-06,转账,1000.00,CNY,,人民币储蓄卡,美元储蓄卡,150.00,,FX transfer
2026-10-07,支出,12.00,USD,餐饮,美元储蓄卡,,,Amazon,USD purchase
```

- Amounts are **positive**, at most two decimals, no currency symbol. An empty currency means `CNY`.
- Kind is `支出` (expense), `收入` (income) or `转账` (transfer).
- Expenses/income need a category; transfers need a destination account and no category.
- `到账金额` (destination amount) is only for cross-currency transfers; leave it blank to convert automatically at the transaction-date rate. Foreign transactions need a cached rate for that date.
- Fees are derived, not a CSV column: importing a wallet transfer recalculates the fee from the account name, amount and date.
- Create matching accounts (same currency) and categories first. Invalid rows are skipped and reported.

### Data & privacy

Default location on Windows:

```text
%LOCALAPPDATA%\FinBoard\
├── finboard.db        # main database
├── finboard-demo.db   # demo database used by --demo
└── finboard.log       # runtime log
```

- Override the data directory with `FINBOARD_DATA_DIR`, or the database file with `FINBOARD_DB`.
- If the profile directory is not writable (portable drive or restricted machine), the app falls back to `FinBoard-Data\finboard.db` beside the executable and shows a notice at startup.
- All books live in a local SQLite file. The only network request fetches public exchange rates from Frankfurter; it contains the requested currency codes and no account, amount or personal information. When offline, the last cached rates remain usable.
- Back up from Settings → Data (or restore an existing snapshot). At startup FinBoard checks integrity and rotates a snapshot into `backups/` when the newest one is over 20 hours old. You can also copy `finboard.db` while the app is closed.

### Design notes

- **Integer cents**: every stored amount is an `int` number of cents; conversion happens only at input/output boundaries.
- **Multi-currency conversion**: rates are stored as `1 CNY = rate` and cross-rates go through CNY. Each transaction keeps its original amount, account posting amount and (for transfers) destination amount; reports convert at the transaction date, so history does not drift with today's rate.
- **Derived balances**: an account balance is opening balance + income − expenses ± transfers, aggregated by SQL. No duplicated balance column to drift out of sync.
- **Transfers**: one transaction row feeds both the source and destination accounts; reports exclude transfers from income/expense.
- **Withdrawal fees**: the transaction row keeps `fee`, `fee_waived` and `fee_included`; `fees.py` computes the fee from the wallet name and the CNY posting amount. A full withdrawal includes the fee in the amount and sends the net, a partial one deducts the fee separately, and a waiver stores zero. Balances, monthly stats and category reports include the fee; CSV imports recalculate it.
- **Recurring rules**: a rule stores only a template and `next_date`; posting is explicit and advances the schedule by one interval. Month-end dates clamp to the target month's last day, and rules stop automatically after their end date.
- **Reconciliation**: the difference between the statement and ledger balances is stored in `accounts.adjustment`, never as a transaction, so income/expense, budgets and category reports stay untouched. Deleting a reconciliation reverses its adjustment.
- **Refund netting**: a refund is still an `income` row, but carries `refund_of_id` pointing to the original expense. Monthly stats, trends, category reports and forecasts subtract refunds from expenses instead of counting them as income, so neither income nor expense is inflated.
- **Automatic rules**: `category_rules` stores a keyword with a unique `lower(pattern) + kind` constraint. Matching is case-insensitive containment with the longest keyword winning; creating a transaction only prefills and hints, hit counts and tag backfills are explicit actions.
- **Backup & restore**: startup runs `PRAGMA quick_check` and creates an online SQLite backup in `backups/` when the newest snapshot is over 20 hours old, keeping 10 by default. Restoring first snapshots the current database and validates the target schema version and integrity.
- **Custom charts**: donut, trend and category bars are painted in `paintEvent` with palette colors and repaint on theme changes.
- **Theme system**: a single `Palette` dataclass drives QPalette, QSS and charts; the choice is stored in `QSettings`.
- **Local-first**: no login, sync or telemetry; only one daily public rate request, and failures never block offline use.

### Testing & build

```bash
# 116 unit tests
python -m unittest discover -s tests

# Core smoke test (temporary DB, demo data, CSV round-trip)
python scripts/smoke_core.py

# UI screenshots (light / dark)
python scripts/smoke_ui.py
python scripts/smoke_ui.py --theme dark

# Windows executable
pip install -r requirements-dev.txt
python -m PyInstaller FinBoard.spec --noconfirm --clean
```

Output: `dist/FinBoard/FinBoard.exe` (one-dir; ship the whole folder).

### Known limitations

- Rates come from Frankfurter (ECB reference rates) and have no separate weekend/holiday quotes; weekend transactions use the latest business day. A transaction dated before the earliest cached rate falls back to that earliest rate, so update rates before backfilling foreign transactions.
- Valuations are available for investment accounts only. A snapshot is treated as the post-close value: transactions dated on or before that day are considered already reflected in it, while later flows adjust the balance.
- Switching the base currency changes aggregation display only; existing budget amounts are not rewritten, so review them after switching.
- Withdrawal fees are calculated only for CNY accounts named “支付宝钱包 / 微信钱包” (or “支付宝 / 微信”). Renaming an account or using a different name disables the rule. The rates are built in and do not update when Alipay/WeChat change their policy. CSV does not carry the waiver/full-withdrawal flags, so imported wallet transfers are recalculated from their amount and account balance; check them after importing.
- Recurring transactions never post in the background; confirm them on the Recurring page. This avoids silently changing the books when a scheduled date passes while the app is closed.
- Reconciliation is available for non-investment accounts only. Use valuation snapshots for investments; deleting a reconciliation reverses its adjustment.
- Fixed assets store purchase price and current value only; there is no depreciation, linked mortgage, disposal or attachments in this version.
- Refunds can only be linked to expense entries, and the total refunded against one expense cannot exceed its amount. Refunds do not count as income and only reduce expenses, so report net totals can differ from the number of entries.
- Automatic rules match by keyword contained in the payee; the longest matching keyword wins. Rules only suggest and prefill when creating or editing a transaction; saved transactions are never rewritten silently, and tag backfilling is manual.
- Automatic backup is enabled by default and keeps up to 10 database snapshots. A backup is created at startup only when the newest one is more than 20 hours old. Backups contain the database only; back up `attachments/` separately.
- The undo log keeps the last 100 actions (new, edit, delete, tag/split change and bulk edit). It survives restarts but is cleared with a full reset.
- Single-user, single-machine: no login, encryption or cloud sync.
- Budgets are per calendar month and roll over only when explicitly enabled; overspending never rolls over.
- No direct bank/Alipay/WeChat sync; use CSV import. Custom CSV rules are used only during import and never modify the source file.
- Splits, tags and attachments are local data. Attachments are copied into the data folder without encryption; back up `attachments/` together with the database.
- CSV duplicate detection uses date, kind, amount, currency, account, destination account and payee, not the note; review these fields before re-importing a file.
- The one-dir build has no self-extraction step; keep `FinBoard.exe` beside its `_internal` folder.
- The English UI translates application copy only; account names, payees, notes and custom category names are user data and stay as entered.

### License

[MIT](LICENSE) © 2026 Urtaome0211
