# MongoDB 问卷系统课程项目

姓名：陈建宇

学号：10245501441

项目仓库：[sakannnna/DMS-majorProject](https://github.com/sakannnna/DMS-majorProject)

这是第一阶段的在线问卷系统：创建者配置并发布问卷，填写者登录后通过链接作答，创建者查看结果。支持单选、多选、文本和数字题，以及配置式校验、条件跳转和匿名填写。

## 双击启动

1. 在项目根目录双击 [start.bat](start.bat)，保留启动窗口。
2. 启动器会检查或启动本机 MongoDB，等待网页就绪后打开浏览器。也可手动打开[问卷工作台](http://127.0.0.1:8009/)。
3. 使用结束后，在启动窗口按 Ctrl+C 停止网页。数据库独立运行，不随网页停止，重启应用不会清空已有问卷和答卷。

启动器复用已有问卷服务，不自动安装依赖；发现端口被其他服务占用会报错。首次换电脑或环境缺失时，再看后面的“环境检查与手动启动”。启动失败的窗口会保留错误信息，先阅读提示，无须直接重装 Python 或 MongoDB。

## 基本使用：用两个账号走一遍

1. **创建者注册并登录**：点击“新建问卷”，填写标题和说明，设置匿名与重复填写策略。
2. **添加题目并保存**：选择题型、输入题干和选项；按需设置必答、数量/长度/数字上下限，以及跳转条件。预览用于检查路线，不保存答卷。
3. **发布并复制链接**：发布后，题目、选项、校验、跳转及填写策略被冻结；标题、说明和截止时间仍可修改。
4. **填写者登录作答**：退出创建者账号，打开分享链接，用另一账号注册或登录；逐题填写，可返回修改。到达结束位置后先进入提交确认，点击提交才保存一份答卷。
5. **创建者查看统计**：切回创建者账号，在自己的列表点击“统计”。页面同时显示答卷份数和去重填写账号数；同一账号重复提交会增加份数，账号数不随之增加。数字平均值按有效答卷计算。
6. **需要时关闭问卷**：关闭后不可重开。仅超过截止时间的已发布问卷可通过延期恢复填写，和“已关闭”不同。

所有填写者均需登录；匿名是对创建者隐藏填写账号，内部仍保留关联用于次数限制。分享链接只授予填写入口，不能查看他人的管理页或统计。默认地址仅供本机演示：另一台设备不能用它的 `127.0.0.1` 访问本机服务。完整权限、跳转和统计边界见需求与设计。

## 材料导航

- [原始作业要求](大作业一第一阶段.docx)：教师需求，保持原文件。
- [工作与记录规范](docs/工作与记录规范.md)：协作流程、文档职责、维护规则和记录模板。
- [需求与设计](docs/需求与设计.md)：唯一的当前需求和总体设计说明，含范围、权限、数据关系和扩展性推演。
- [AI 使用日志](docs/AI使用日志.md)：提示词摘要、用户决定、AI 产出定位及实际验证记录。
- [API 使用说明](docs/API说明.md)：调用示例、请求输出契约和前端字段依赖。
- [测试记录](docs/测试记录.md)：用例步骤、输入、预期、实际结果及证据。
- [阶段一报告](docs/阶段一报告.md)：已有报告材料；正文由用户后续审阅与撰写。

## 启动和交付前检查

先确认网页可以打开；这证明正在运行的服务可访问。需要快速验证业务主流程时，在项目根目录的 PowerShell 执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -k T23 --junitxml=docs/evidence/T23-smoke.xml
```

T23是冒烟检查，即用一条完整路线快速检查创建、发布、填写、提交、统计是否接通。它通过进程内API和真实MongoDB独立测试库执行，不能代替对8009端口实际网页的访问检查，也不等于完成了网页点击测试。

交付前可运行全量测试：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --junitxml=docs/evidence/pytest.xml
```

测试会创建并清理随机独立测试库，不清空普通业务库。T24另检查100账号、最多10个工作线程的提交正确性；单独运行时把筛选改为 `-k T24`，输出改为 `docs/evidence/T24-correctness.xml`。其结果不表示压力极限或真实在线人数。关键输入、预期、耗时和已有证据统一见[测试记录](docs/测试记录.md)。运行命令会更新输出文件，保存新结果时应同时记录版本，不能继续沿用旧证据说明。

## 环境检查与手动启动

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

端口已监听时先访问页面和 `/openapi.json` 核对是否为本项目服务，不重复启动；只有端口检查不能证明服务正确。服务不可达时再检查 `.local/web.stderr.log`（若使用了后台启动）和 MongoDB 日志。

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

## 按需准备演示数据

通常可直接使用上面的两账号步骤。需要可复现示例时，在网页服务启动后运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/demo.py
```

工具交互读取账号密码，通过正式接口创建包含四种输入和三类跳转的问卷；已有同名示例时不覆盖。它会在所连接服务的业务库中留下示例问卷，和运行后清理的自动测试库不同。默认连接本机8009；可通过 `SURVEY_BASE_URL` 指向自己的服务。请勿在测试证据中记录密码或会话Cookie。

## 代码和阶段基线

- [请求模型](app/models.py)、[输出模型](app/contracts.py)：由路由生成输入输出API契约。
- [数据库初始化](app/database.py)：四集合 schema validator、索引及序列化。
- [校验与跳转](app/logic.py)：独立于网页的规则检查与路径重放。
- [账号安全](app/security.py)、[应用接口](app/main.py)：认证、权限和业务操作。
- [页面模板](app/templates/index.html)、[页面交互](app/static/app.js)、[样式](app/static/style.css)：简单网页。
- [自动测试](tests/test_system.py)、[依赖版本](requirements.txt)、[数据库启动脚本](scripts/start-db.ps1)。

Git 标签 `stage1-v1` 保存第一阶段早期交付基线，不含之后所有修复与统计口径调整；`stage1-final` 标记本次第一阶段提交版。验证版本与证据见测试记录。第二阶段在此代码上扩展，先处理真实需求变更、旧数据兼容与回归，不能通过删除数据库或重写另一个系统替代原成果。


## 变更收尾

按[工作规范](docs/工作与记录规范.md)在每批相关代码变更中完成契约、前端消费与对应文档检查；接口回归包含T19。本地链接检查使用[文档检查脚本](scripts/check-docs.py)，默认只检查Git工作树中变更的Markdown，也可传入本批相关文档路径。不要为每次检查新建报告，实际结果进入AI日志。
