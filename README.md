# 工作任务台账管理软件

一个开箱即用的本地任务台账系统：按表格列自动生成数据结构与表单，支持任务的增删改查、
筛选排序、日历联动、到期提醒与逾期高亮、本地持久化与 Excel/CSV 批量导入导出。

技术栈：Python 3.9+ / FastAPI / SQLite / 原生 HTML+CSS+JS（无需 Node 构建）。

---

## 一、功能总览

| 模块 | 说明 |
| --- | --- |
| 任务台账 | 增删改查、关键词搜索、多条件筛选（负责人/状态/任务划分/截止区间/仅看逾期）、分页；列表按截止日期升序固定排序 |
| 单元格内联编辑 | 任务名称、负责人、任务划分、完成状态、开始/结束时间、备注（以及导入产生的扩展字段）支持在列表里**点击或双击**直接编辑：回车或失焦保存、Esc 取消；保存前做非空、长度、日期先后校验，校验失败保留原值并提示 |
| 字段自适应 | 内置字段来自《任务汇总》表头（任务名称/任务划分/完成状态/开始时间/结束时间/备注），导入新表格时未知列自动注册为新字段，列表与表单自动扩展 |
| 日历联动 | 月历视图展示任务起止日期；生成标准 `.ics` 文件可导入 macOS「日历」/Outlook/手机日历；提供 `/api/calendar/feed.ics` 订阅地址持续同步；一键唤起系统日历 |
| 提醒功能 | 每个任务可单独设置提前量（到期时/提前 10 分钟~1 周），也可用全局默认；后台线程轮询触发 macOS 通知中心等桌面通知；逾期任务列表红色高亮；支持"稍后提醒"顺延 |
| 数据持久化 | SQLite 本地存储（`data/tasks.db`，WAL 模式），设置保存于 `data/settings.json`；一键备份到 `data/backups/` |
| 导入导出 | 支持 `.xlsx / .xlsm / .csv` 导入（追加 / 按任务名称更新 / 清空重导，导入前可预览列映射）；导出 Excel（带表头样式、冻结首行、自动筛选）与 CSV；可下载导入模板 |
| 统计概览 | 总数、完成率、逾期数、7 日内到期、按状态/划分/负责人分布图 |

---

## 二、目录结构

```
task-ledger/
├── start.py                  # 启动入口（python start.py 即可运行）
├── requirements.txt          # 依赖清单
├── README.md
├── app/                      # 后端（FastAPI）
│   ├── main.py               # 路由与静态页面托管
│   ├── config.py             # 全局配置与设置持久化（提醒默认值等）
│   ├── fields.py             # 字段注册表：表格列 → 数据结构/表单（含表头别名映射）
│   ├── db.py                 # SQLite 建库、迁移、自定义字段、备份
│   ├── crud.py               # 任务增删改查、筛选排序分页、统计
│   ├── importer.py           # xlsx/csv 导入（表头自动识别、未知列自动注册）
│   ├── exporter.py           # xlsx/csv 导出与导入模板
│   ├── ics.py                # 生成 .ics（含 VALARM 提醒）、唤起系统日历
│   ├── reminders.py          # 提醒引擎：扫描、桌面通知、后台轮询线程
│   └── utils.py              # 日期解析/格式化等工具
├── web/                      # 前端（原生实现，无构建步骤）
│   ├── index.html
│   ├── css/style.css
│   └── js/{api.js, app.js, calendar.js}
├── TaskLedger.app/           # macOS 双击启动的 App 捆绑包（make_app.sh 重建）
├── 停止台账.command           # 双击停止后台服务
├── run.sh                    # 命令行一键启动脚本（前台运行）
├── scripts/
│   ├── import_xlsx.py        # 命令行导入工具（首次建库用）
│   ├── make_icon.py          # 纯 Python 生成应用图标
│   └── make_app.sh           # 重建 TaskLedger.app
└── data/                     # 运行时生成
    ├── tasks.db              # SQLite 数据库
    ├── settings.json         # 本地设置
    ├── server.pid            # 双击启动时的服务进程号
    ├── 任务台账.ics           # 自动生成的日历同步文件
    ├── logs/                 # 双击启动的运行日志
    └── backups/              # 自动备份（保留最近 10 份）
```

---

## 三、安装与启动

### 方式一：双击启动（macOS 推荐）

双击项目根目录的 **`TaskLedger.app`**（或桌面上的「任务台账」快捷方式）：

- 无需终端窗口，服务在后台启动并自动打开浏览器；
- 已在运行时再次双击，只会重新打开浏览器，不会重复启动；
- 停止服务：双击项目根目录的 **`停止台账.command`**；
- 日志与 PID 记录在 `data/logs/` 与 `data/server.pid`；
- 支持环境变量：`TASK_LEDGER_HOME`（项目目录）、`TASK_LEDGER_PORT`（端口）、`TASK_LEDGER_HOST`（地址）。

App 本体（`TaskLedger.app/`）需保留在项目目录内；如需放到「应用程序」文件夹，请改为在桌面保留快捷方式。重建 App 捆绑包：`./scripts/make_app.sh`。

### 方式二：命令行启动（跨平台，参数完整保留）

```bash
cd task-ledger

# 1. 创建虚拟环境并安装依赖（也可以直接 pip install -r requirements.txt）
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt      # Windows: .venv\Scripts\pip install ...

# 2. 启动（自动打开浏览器）
.venv/bin/python start.py                       # Windows: .venv\Scripts\python start.py

# 可选参数
.venv/bin/python start.py --port 9000           # 指定端口
.venv/bin/python start.py --host 0.0.0.0        # 允许局域网访问
.venv/bin/python start.py --no-browser          # 不自动打开浏览器
```

两种方式行为一致：同一份 SQLite 数据、同一端口（默认 8765）、同一套启动参数。启动后访问 <http://127.0.0.1:8765>。

### 登录与退出

- **首次启动**：显示「创建本机账号」页（用户名 + 密码），账号以 PBKDF2 加盐哈希保存在本机 `data/auth.json`，不上传任何服务器；
- **启动流程**：启动画面（品牌展示 + 初始化进度）→ 连接本地服务 → 校验登录状态 → 已登录直接进入主界面，未登录进入登录页（勾选「记住我」30 天内免登录）；
- **退出登录**：顶栏头像菜单 → 退出登录（有确认提示），清除服务端会话与本地缓存后返回登录页；
- **退出应用**：顶栏头像菜单 → 退出应用（红色危险操作 + 确认提示），关闭本地服务并清理全部会话，页面显示「应用已退出」；
- **异常处理**：本地服务未就绪时启动画面给出「重试 / 查看帮助」；会话过期后任意接口返回 401，自动回到登录页；登录失败限速（连续 5 次锁定 60 秒）；
- **忘记密码**：关闭应用后删除 `data/auth.json` 再启动即可重新建号，任务数据不受影响。

**首次导入数据**（二选一）：

- 界面操作：任务列表 →「导入表格」→ 拖入表格文件 → 确认列映射 → 开始导入；
- 命令行：`.venv/bin/python scripts/import_xlsx.py "/path/任务汇总.xlsx"`。

> 当前 `data/tasks.db` 已预置《任务汇总》中的 102 条任务。

---

## 四、日历联动说明

1. **应用内月历**：「日历视图」按月展示任务，红色=已逾期、橙色=即将到期、绿色=已完成；
2. **同步到系统日历**：点击「同步到系统日历」，会生成 `data/任务台账.ics` 并调用系统
   默认程序打开（macOS 会弹出「日历」导入面板，选择目标日历即可）；
3. **订阅方式（推荐，可自动更新）**：系统日历 → 新建日历订阅 → 填入
   `http://127.0.0.1:8765/api/calendar/feed.ics`，之后任务增删改会自动同步；
4. `.ics` 中的 VALARM 与任务提醒提前量一致，系统日历端也会弹提醒。

---

## 五、提醒功能说明

- 提前量选项：到期时 / 提前 10 分钟、30 分钟、1/2/6/12 小时 / 提前 1/2/3 天 / 提前 1 周；
- 全局默认在「设置」中调整，单个任务可在表单“提醒设置”里单独覆盖；
- 触达方式：macOS 通知中心（`osascript`）、Linux `notify-send`、Windows 气泡通知；
  同时应用内「提醒」按钮会汇总全部逾期与即将到期任务，支持查看/稍后提醒/一键标记完成；
- 已完成的任务不再提醒；改期或修改提前量后会重新生效；「稍后提醒」按设置的顺延时间（默认 30 分钟）再次提醒。

> 提示：macOS 首次通知可能需要在「系统设置 → 通知」中允许终端 App 发送通知。

---

## 六、常用接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/tasks` | 任务列表（支持 q/owner/status/priority/due_from/due_to/overdue_only/page/page_size；排序固定为截止日期升序） |
| POST / PUT / DELETE | `/api/tasks[/{id}]` | 新建 / 修改 / 删除 |
| GET | `/api/fields` | 字段注册表（前端据此生成表单与列） |
| POST | `/api/import`、`/api/import/preview` | 导入与导入预览 |
| GET | `/api/export?format=xlsx\|csv`、`/api/export/template` | 导出与模板 |
| GET | `/api/calendar/month`、`/api/calendar/feed.ics`、`/api/calendar/ics` | 日历月数据、订阅源、下载 |
| GET | `/api/reminders/check`、POST `/api/reminders/snooze/{id}` | 提醒检查、稍后提醒 |
| GET / PUT | `/api/settings` | 读写设置 |

---

## 七、数据与备份

- 所有数据保存在本地 `data/tasks.db`（SQLite），迁移只需复制 `data/` 目录；
- 「设置 → 数据管理 → 立即备份数据库」随时手动备份，清空/覆盖导入前会自动备份；
- 备份保留最近 10 份，位于 `data/backups/`；
- **隐私说明**：`data/` 目录（数据库、设置、备份、日历文件）已在 `.gitignore` 中排除，
  不会随代码提交到版本库；`data/` 目录在程序启动时自动创建。
