# 贡献指南

感谢你关注这个本地任务台账项目。本文件说明如何搭建开发环境、提交改动，以及需要遵守的基本约定。

## 开发环境

- Python 3.9+；无需 Node 构建步骤（前端为原生 HTML/CSS/JS）。
- 创建虚拟环境并安装依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

- 启动开发服务（默认端口 8765）：

```bash
.venv/bin/python start.py --no-browser
```

## 项目结构约定

- 后端逻辑在 `app/`，路由集中在 `app/main.py`，数据库与迁移在 `app/db.py`，业务逻辑在 `app/crud.py`。
- 前端在 `web/`，`app.js` 为 IIFE，无模块化构建；`index.html` 中的静态资源通过 `?v=` 参数控制缓存。
- 新增字段需同时考虑 `app/fields.py` 字段注册表、`app/db.py` 迁移和前端表单渲染。

## 提交改动

1. 一个提交只做一件事，提交信息简短明确（例如「修复：逾期筛选时区偏移」）。
2. 涉及数据库结构变更时，必须在 `app/db.py` 中补充幂等迁移，保证旧库可平滑升级。
3. 涉及界面改动时，同步更新 `web/index.html` 的静态资源版本号，并确认浅色/暗色两种主题下均可读。
4. 在 `CHANGELOG.md` 顶部追加本次变更说明；功能或版本变化同步更新 `app/main.py` 的 `APP_VERSION`。
5. **不要提交任何本地数据**：`data/` 已被 `.gitignore` 排除，请勿使用 `git add -f` 强制加入数据库、账号文件、备份或日历文件。

## 验证方式

项目目前没有自动化测试套件，请在提交前至少完成以下人工验证：

- `python -m compileall app` 与 `node --check web/js/app.js` 通过；
- 在隔离端口启动实例（如 `TASK_LEDGER_PORT=8799`），用浏览器实际走过改动涉及的流程；
- 分别检查浅色与暗色主题、任务列表与详情展开、导入导出等关联功能未受影响。

## Issue 与 Pull Request

- 提 Issue 时请说明：期望行为、实际行为、复现步骤、操作系统与 Python 版本；如涉及界面问题请附截图。
- Pull Request 请描述改动的动机、影响范围和验证结果；首次贡献建议先从文档或小修复入手。

## 许可证

提交即表示你同意所贡献内容按本项目的 [MIT 许可证](LICENSE) 发布。
