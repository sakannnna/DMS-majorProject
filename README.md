# MongoDB 问卷系统课程项目

第一阶段实现按已确认的需求运行。当前功能与扩展边界见需求与设计，验证结果见测试记录，提交核对见阶段报告；本页只维护入口、运行和检查方法。

## 文档入口

- [原始作业要求](大作业一第一阶段.docx)：教师需求，保持原文件。
- [工作与记录规范](docs/工作与记录规范.md)：协作流程、文档职责、维护规则和记录模板。
- [需求与设计](docs/需求与设计.md)：唯一的当前需求和总体设计说明，含范围、权限、数据关系和扩展性推演。
- [AI 使用日志](docs/AI使用日志.md)：提示词摘要、用户决定、AI 产出定位及实际验证记录。
- [API 使用说明](docs/API说明.md)：请求约定、输出契约和前端字段依赖；模型生成OpenAPI。
- [测试记录](docs/测试记录.md)：用例步骤、输入、预期、实际结果及证据。
- [阶段一报告](docs/阶段一报告.md)：完成情况、交付核对、问题解决及第二阶段基线。

## 本机运行

先检查已有 Python 与项目环境，避免重复安装。数据库启动脚本默认使用 `D:\MongoDB\Server\bin\mongod.exe`；路径不同时按下文传参。以下命令在本目录的 PowerShell 运行：

```powershell
python --version
Test-Path .venv\Scripts\python.exe
Test-Path D:\MongoDB\Server\bin\mongod.exe
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @(27019,8009) }
```

环境可用且对应端口未启动服务时运行：

```powershell
.\scripts\start-db.ps1
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8009
```

打开 [问卷工作台](http://127.0.0.1:8009/)，首次使用可注册自己的账号。问卷管理页可配置题目、预览、发布并复制填写链接。关闭网页服务可在运行它的终端按 Ctrl+C。端口已监听时先访问页面和 `/openapi.json` 核对是否为本项目服务，不重复启动；只有端口检查不能证明服务正确。服务不可达时再检查 `.local/web.stderr.log`（若使用了后台启动）和 MongoDB 日志。

数据库启动脚本仅绑定 127.0.0.1:27019，数据位于 `.local/mongo`，日志为 `.local/mongodb.log`；它复用 D 盘可执行文件，不安装 Windows 服务。脚本检测端口已监听时不再启动，应用启动会实际 ping 数据库。应用默认数据库为 `survey_course`，自动建立四集合 validator 和索引，重启不重置数据。

| 配置项 | 默认值和用途 |
| --- | --- |
| MONGODB_URI | `mongodb://127.0.0.1:27019`；已有其他 MongoDB 实例时可改用其连接串 |
| MONGODB_DB | `survey_course`；业务数据库名称，仅允许字母数字下划线 |
| COOKIE_SECURE | `0` 供本地 HTTP 演示；HTTPS 部署设为 `1` |
| SURVEY_BASE_URL | `http://127.0.0.1:8009`；示例生成工具调用的服务地址 |

可在启动前设置环境变量，例如 `$env:MONGODB_URI = 'mongodb://127.0.0.1:27017'`。业务账号、会话、问卷和答卷均在 MongoDB；配置及进程日志不充当业务存储。默认提供本机演示，分享链接需要接收者能访问同一服务；未提供公网部署配置。

## 迁移或重建环境

先检查现有 Python 和所选环境中的依赖。仅当项目虚拟环境缺失或确需隔离时才创建；仅在缺失或版本不匹配时安装锁定依赖。不重复下载安装 Python 或 MongoDB。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

若已有兼容环境可直接使用其 Python 替代 `.venv\Scripts\python.exe`。MongoDB 在其他位置时使用 `.\scripts\start-db.ps1 -Mongod '完整路径\mongod.exe'`，或提供已有实例的 URI。`.venv` 和 `.local` 不纳入交付基线；保留代码、锁定依赖和准备方法即可重建。

## 验证和演示数据

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --junitxml=docs/evidence/pytest.xml
.\.venv\Scripts\python.exe -X utf8 scripts/demo.py
```

测试会生成并清理随机独立测试库，不清空普通业务库。示例工具会交互读取账号密码，首次使用注册账号，通过正式接口创建包含四种输入和三类跳转的问卷；检测到已有同名示例时不覆盖。测试代码和[示例脚本](scripts/demo.py)同时提供可复现的数据准备方法。使用演示数据时先登录检查自己的列表，或运行示例脚本按需创建；验证证据见测试记录。

## 代码和阶段基线

- [请求模型](app/models.py)、[输出模型](app/contracts.py)：由路由生成输入输出API契约。
- [数据库初始化](app/database.py)：四集合 schema validator、索引及序列化。
- [校验与跳转](app/logic.py)：独立于网页的规则检查与路径重放。
- [账号安全](app/security.py)、[应用接口](app/main.py)：认证、权限和业务操作。
- [页面模板](app/templates/index.html)、[页面交互](app/static/app.js)、[样式](app/static/style.css)：简单网页。
- [自动测试](tests/test_system.py)、[依赖版本](requirements.txt)、[数据库启动脚本](scripts/start-db.ps1)。

Git 标签 `stage1-v1` 保存第一阶段代码、原始要求、文档及必要证据。第二阶段在此代码上扩展，先处理真实需求变更、旧数据兼容与回归，不能通过删除数据库或重写另一个系统替代原成果。


## 变更收尾

按[工作规范](docs/工作与记录规范.md)在每批相关代码变更中完成契约、前端消费与对应文档检查；接口回归包含T19。本地链接检查使用[文档检查脚本](scripts/check-docs.py)，默认只检查Git工作树中变更的Markdown，也可传入本批相关文档路径。不要为每次检查新建报告，实际结果进入AI日志。
