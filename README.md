# MongoDB 问卷系统课程项目

姓名：陈建宇

学号：10245501441

项目仓库：[sakannnna/DMS-majorProject](https://github.com/sakannnna/DMS-majorProject)

这是在第一阶段基础上扩展的在线问卷系统：创建者配置并发布问卷，填写者登录后通过链接作答，创建者查看结果。支持单选、多选、文本和数字题，以及配置式校验、条件跳转和匿名填写。

第二阶段已接通独立题目、不可变版本、共享、个人题库、使用追踪和跨问卷统计。旧数据升级方法见后面的“旧库显式升级”；见[需求与设计](docs/需求与设计.md)中的第二阶段章节及[新增需求原文](大作业一：需求变更.docx)。运行及验证边界以当前说明为准。

## 双击启动

1. 在项目根目录双击 [start.bat](start.bat)，保留启动窗口。
2. 启动器会检查或启动本机 MongoDB，等待网页就绪后打开浏览器。也可手动打开[问卷工作台](http://127.0.0.1:8009/)。
3. 使用结束后，在启动窗口按 Ctrl+C 停止网页。数据库独立运行，不随网页停止，重启应用不会清空已有问卷和答卷。

启动器复用已有问卷服务，不自动安装依赖；发现端口被其他服务占用会报错。首次换电脑或环境缺失时，再看后面的“环境检查与手动启动”。启动失败的窗口会保留错误信息，先阅读提示，无须直接重装 Python 或 MongoDB。

## 首次运行或换电脑

推荐 Windows 10/11 64位、Python 3.12、MongoDB Community Server，以及新版 Chrome 或 Edge。本次换环境检查使用 Windows 11、Python 3.12 和 MongoDB 8.3.11；其他操作系统及 Python/MongoDB 版本未逐一验证。MongoDB Compass 是管理工具，不能代替数据库服务端。网页资源随源码提供，不依赖外部 CDN；浏览器通过本机 HTTP 服务访问，不能直接双击 HTML 文件。

1. 先完整解压 ZIP 到本机可写目录，再打开该目录的 PowerShell。不要在压缩包内直接启动，也不要复制另一台电脑的 `.venv` 或 `.local`。
2. 已有 Python 3.12 时，确认 `python --version`，然后准备本项目环境：

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m pip check
   ```

3. 安装或使用已有 MongoDB Server。启动器依次查找 `MONGOD_EXE`、PATH、`C:\Program Files\MongoDB\Server\<版本>\bin`（按实际 Program Files 位置），最后兼容原 D 盘路径。自定义目录可在同一窗口设置：

   ```powershell
   $env:MONGOD_EXE = 'C:\你的MongoDB目录\bin\mongod.exe'
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-db.ps1 -CheckOnly
   .\start.bat
   ```

   自动找到服务端时不必设置 `MONGOD_EXE`。若已有 MongoDB 服务使用27017，可改设 `$env:MONGODB_URI = 'mongodb://127.0.0.1:27017'` 后运行 `start.bat`，不会另启动27019实例。带认证的实例应提供有本项目建库和索引权限的连接串。
4. 首次使用空库会自动创建集合和索引，页面中自行注册两个账号即可验证；包内不附本机账号或数据。导入旧库时先按“旧库显式升级”处理。

启动器仅用于 Windows。macOS/Linux 可创建本机虚拟环境、安装相同依赖，启动 MongoDB 后设置 `MONGODB_URI`，用 `python -m uvicorn app.main:app --host 127.0.0.1 --port 8009` 手动运行；未在这些系统实测。Node.js 和 Git 不参与正常网页运行，只有部分自动测试/打包检查需要。 首次安装依赖需要可用网络或本地包缓存；正常网页运行不要求外网。GitHub的Download ZIP不包含Git历史，可用于运行应用；要执行旧版本保护测试，应使用完整交付包，或用Git克隆并取得标签。默认仅本机访问，跨设备访问和公网部署不在本次交付配置内。

## 基本使用：用两个账号走一遍

1. **创建者注册并登录**：点击“新建问卷”，填写标题和说明，设置匿名与重复填写策略。
2. **添加题目并保存**：点击“添加题目”→“新建普通题”，选择题型、输入题干和选项；按需设置必答、数量/长度/数字上下限，以及跳转条件。预览用于检查路线，不保存答卷。
3. **发布并复制链接**：发布后，题目、选项、校验、跳转及填写策略被冻结；标题、说明和截止时间仍可修改。
4. **填写者登录作答**：退出创建者账号，打开分享链接，用另一账号注册或登录；逐题填写，可返回修改。到达结束位置后先进入提交确认，点击提交才保存一份答卷。
5. **创建者查看统计**：切回创建者账号，在自己的列表点击“查看统计”。页面同时显示答卷份数和去重填写账号数；同一账号重复提交会增加份数，账号数不随之增加。数字平均值按有效答卷计算。
6. **复用题目（第二阶段）**：顶部“题目中心”→“我的题目”可新建、保存草稿或正式版；打开题目后直接查看内容，在上方选择准确版本。基于旧版编辑生成新版本，“更多”中可用此版内容生成新版本。问卷的“添加题目”弹窗可从本人、共享、题库连续选入；同一版可选多次，必答和跳转独立设置。草稿可主动换版，发布后冻结。旧卷的“另存为可复用题目”只保存题目内容，旧答案仍留在原卷统计。
7. **共享与分类**：打开题目、选定准确版本后切到“共享管理”页签，输入已注册用户名授权；接收者在“共享给我”查看、派生或加入个人题库。问卷选题可从本人题目、共享版本或题库进入。撤销共享会阻止新选用，已有草稿和已拥有的派生题保留。
8. **追踪和跨卷统计**：题目详情的“使用情况”只列本人问卷；同页“跨问卷统计”显示准确版本的回答条数、答卷份数及去重账号数，可筛选问卷、翻页查看明细和数字分布。原问卷管理页也能进入此前已选用版本的统计。
9. **需要时关闭问卷**：关闭后不可重开。仅超过截止时间的已发布问卷可通过延期恢复填写，和“已关闭”不同。

所有填写者均需登录；匿名是对创建者隐藏填写账号，内部仍保留关联用于次数限制。分享链接只授予填写入口，不能查看他人的管理页或统计。默认地址仅供本机演示：另一台设备不能用它的 `127.0.0.1` 访问本机服务。完整权限、跳转和统计边界见需求与设计。

## 材料导航

- [原始作业要求](大作业一第一阶段.docx)：教师需求，保持原文件。
- [工作与记录规范](docs/工作与记录规范.md)：协作流程、文档职责、维护规则和记录模板。
- [需求与设计](docs/需求与设计.md)：唯一的当前需求和总体设计说明，含范围、权限、数据关系和扩展性推演。
- [AI 使用日志](docs/AI使用日志.md)：提示词摘要、用户决定、AI 产出定位及实际验证记录。
- [API 使用说明](docs/API说明.md)：调用示例、请求输出契约和前端字段依赖。
- [测试记录](docs/测试记录.md)：用例步骤、输入、预期、实际结果及证据。
- [阶段一报告](docs/阶段一报告.md)：项目完成报告的可编辑正文；[PDF提交版](output/pdf/2026_ECNU_PJ1_1_陈建宇.pdf)按课程平台规则命名，正文修改后需重新导出。
- [阶段二报告](docs/阶段二报告.md)：需求变更、原系统扩展、兼容与测试的成果说明；[第二阶段PDF](output/pdf/2026_ECNU_PJ1_2_陈建宇.pdf)供审阅和提交。
- 第二阶段完整交付包 `output/delivery/2026_ECNU_PJ1_2_陈建宇.zip`：当前代码、文档、测试、报告及必要历史基线，排除本机数据库与环境。

## 启动和交付前检查

先确认网页可以打开；这证明正在运行的服务可访问。需要快速验证业务主流程时，在项目根目录的 PowerShell 执行：

```powershell
.\.venv\Scripts\python.exe -X utf8 -m pytest -q -k T23 --junitxml=docs/evidence/stage2-delivery-smoke.xml
```

T23是冒烟检查，即用一条完整路线快速检查创建、发布、填写、提交、统计是否接通。它通过进程内API和真实MongoDB独立测试库执行，不能代替对8009端口实际网页的访问检查，也不等于完成了网页点击测试。

交付前可运行全量测试：

```powershell
$env:SURVEY_TEST_EVIDENCE_PREFIX = 'stage2-delivery-'
.\.venv\Scripts\python.exe -X utf8 -m pytest -q --junitxml=docs/evidence/stage2-delivery-regression.xml
```

测试会创建并清理随机独立测试库，不清空普通业务库。T24另检查100账号、最多10个工作线程的提交正确性；单独运行时把筛选改为 `-k T24`，输出改为 `docs/evidence/T24-correctness.xml`。其结果不表示压力极限或真实在线人数。关键输入、预期、耗时和已有证据统一见[测试记录](docs/测试记录.md)。测试代码的缺省计时JSON仍为stage2-part2-前缀；交付前按上面的命令显式改用stage2-delivery-前缀，不覆盖第一阶段同名专项证据；可用SURVEY_TEST_EVIDENCE_PREFIX调整前缀。运行命令会更新本批输出文件，保存新结果时应同时记录版本，不能继续沿用旧证据说明。

## 环境检查与手动启动

先检查已有 Python 与项目环境，避免重复安装。数据库启动脚本支持自动发现，也可用 `MONGOD_EXE` 或 `-Mongod` 指定路径。以下命令在本目录的 PowerShell 运行：

```powershell
python --version
Test-Path .venv\Scripts\python.exe
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-db.ps1 -CheckOnly
Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -in @(27019,8009) }
```

环境可用且对应端口未启动服务时运行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-db.ps1
.\.venv\Scripts\python.exe -X utf8 -m uvicorn app.main:app --host 127.0.0.1 --port 8009
```

端口已监听时先访问页面和 `/openapi.json` 核对是否为本项目服务，不重复启动；只有端口检查不能证明服务正确。服务不可达时再检查 `.local/web.stderr.log`（若使用了后台启动）和 MongoDB 日志。

数据库启动脚本仅绑定 127.0.0.1:27019，数据位于 `.local/mongo`，日志为 `.local/mongodb.log`；它复用已有服务端可执行文件，不安装 Windows 服务。脚本检测端口已监听时不再启动，应用启动会实际 ping 数据库。应用默认数据库为 `survey_course`；空库建立当前九集合及索引，已有第一阶段或第二阶段第一部分库必须先显式升级，重启不重置数据。

| 配置项 | 默认值和用途 |
| --- | --- |
| MONGODB_URI | `mongodb://127.0.0.1:27019`；已有其他 MongoDB 实例时可改用其连接串 |
| MONGODB_DB | `survey_course`；业务数据库名称，仅允许字母数字下划线 |
| COOKIE_SECURE | `0` 供本地 HTTP 演示；HTTPS 部署设为 `1` |
| SURVEY_BASE_URL | `http://127.0.0.1:8009`；示例生成工具调用的服务地址 |

可在启动前设置环境变量，例如 `$env:MONGODB_URI = 'mongodb://127.0.0.1:27017'`。业务账号、会话、问卷和答卷均在 MongoDB；配置及进程日志不充当业务存储。默认提供本机演示，分享链接需要接收者能访问同一服务；未提供公网部署配置。

## 旧库显式升级

第一次用当前程序打开第一阶段或第二阶段第一部分旧库前，停止网页服务及其他数据库写入者，启动MongoDB后执行下列命令。脚本先预检，再备份所有文档、集合校验与索引，备份成功才升级；不改写旧问卷或答卷。已升级后可重跑，但每次使用新的备份目录。不应通过删库解决版本错误。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/upgrade-db.py --app-stopped --backup-dir .local/backups/before-stage2-part2
.\start.bat
```

脚本按MONGODB_URI/MONGODB_DB选择数据库。目录已存在时拒绝覆盖；中断后仍保持服务停止，使用另一新目录重跑。未知结构先拒绝；不完整升级不能对外提供写入。备份目录含业务及认证数据，应留在本机，不加入提交材料。

需要回退时，先停止新版，把原备份恢复到一个**全新空库**，再让对应旧程序连接该库；不直接降级现库validator。以下为恢复命令示例，不会删除原库；原库升级后产生的新数据不会自动出现在旧备份中。

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/upgrade-db.py --app-stopped --backup-dir .local/backups/before-stage2-part2 --restore-into survey_course_restored
# 在启动对应旧版本前设置：
$env:MONGODB_DB = 'survey_course_restored'
```

## 迁移或重建环境

先检查现有 Python 和所选环境中的依赖。仅当项目虚拟环境缺失或确需隔离时才创建；仅在缺失或版本不匹配时安装锁定依赖。不重复下载安装 Python 或 MongoDB。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

若已有兼容环境可直接使用其 Python 替代 `.venv\Scripts\python.exe`。MongoDB 在其他位置时使用 `powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-db.ps1 -Mongod '完整路径\mongod.exe'`，或提供已有实例的 URI。`.venv` 和 `.local` 不纳入交付基线；保留代码、锁定依赖和准备方法即可重建。

## 按需准备演示数据

通常可直接使用上面的两账号步骤。需要可复现示例时，在网页服务启动后运行：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts/demo.py
```

工具交互读取账号密码，通过正式接口创建包含四种输入和三类跳转的问卷；已有同名示例时不覆盖。它会在所连接服务的业务库中留下示例问卷，和运行后清理的自动测试库不同。默认连接本机8009；可通过 `SURVEY_BASE_URL` 指向自己的服务。请勿在测试证据中记录密码或会话Cookie。

## 代码和阶段基线

- [请求模型](app/models.py)、[输出模型](app/contracts.py)：由路由生成输入输出API契约。
- [数据库初始化](app/database.py)：当前九集合validator、兼容预检、索引及序列化；[显式升级/备份恢复](scripts/upgrade-db.py)负责旧库接入。
- [校验与跳转](app/logic.py)：独立于网页的规则检查与路径重放。
- [账号安全](app/security.py)、[应用接口](app/main.py)：认证、权限和业务操作。
- [独立题目与版本](app/reusable.py)、[问卷位置统一保存](app/survey_questions.py)：独立题目与位置保存逻辑。
- [共享、题库与跨卷统计](app/question_management.py)：准确版本授权、个人分类、本人使用查询及三口径统计。
- [页面模板](app/templates/index.html)、[页面交互](app/static/app.js)、[样式](app/static/style.css)：简单网页。
- [自动测试](tests/test_system.py)、[依赖版本](requirements.txt)、[数据库启动脚本](scripts/start-db.ps1)。

Git 标签 `stage1-v1` 保存第一阶段早期交付基线，不含之后所有修复与统计口径调整；`stage1-final` 标记本次第一阶段提交版。验证版本与证据见测试记录。第二阶段在此代码上扩展，先处理真实需求变更、旧数据兼容与回归，不能通过删除数据库或重写另一个系统替代原成果。


## 变更收尾

按[工作规范](docs/工作与记录规范.md)在每批相关代码变更中完成契约、前端消费与对应文档检查；接口回归包含T19。本地链接检查使用[文档检查脚本](scripts/check-docs.py)，默认只检查Git工作树中变更的Markdown，也可传入本批相关文档路径。不要为每次检查新建报告，实际验证结果进入测试记录；未经要求不自动记录AI日志。


## 第二阶段交付核对

第二阶段功能实现为0ecc601，历史AI日志提交为ef27f33；最终代码、前端整理、报告和交付说明以 `stage2-final` 标签标记。源码及报告哈希和实际验证范围见docs/evidence/stage2-delivery-version.json。

| 作业提交项 | 包内位置 |
| --- | --- |
| 后端、网页与MongoDB结构 | app/，含database.py和question_management.py |
| 配置、依赖与启动 | requirements.txt、start.bat、scripts/及本README |
| 系统、数据库、接口和关键逻辑 | docs/需求与设计.md、docs/API说明.md |
| 测试步骤、输入、输出、实际结果 | tests/test_system.py、docs/测试记录.md、docs/evidence/ |
| AI日志与报告中的使用说明 | docs/AI使用日志.md、docs/阶段二报告.md第六节 |
| 完成报告及第一阶段成果 | docs/两阶段报告、output/pdf/两份PDF；Git标签stage1-final |

交付ZIP包含由已提交历史生成的独立.git元数据，供T20/T33/T40实际调用旧初始化代码；不含原工作区的Git配置、钩子或操作日志。源码和文档来自最终提交的工作文件。解压后先看本README，运行环境缺失时按环境章节准备；不附虚拟环境、MongoDB可执行文件或业务数据。版本保护测试还需本机Git命令可用。

PDF和ZIP名称沿用已有第一阶段命名方式，将阶段标识改为2；需求docx未给出第二阶段专用上传命名细则，课程平台如有不同要求应以平台为准。提交前请审阅第二阶段报告中的AI贡献和业务解释，确认平台命名及是否要求单独上传PDF；无需为此改系统代码。报告正文更新后须重新导出PDF并重打交付包，不让三个副本失去对应。


本次范围保持为个人题目/版本、指定账号共享、个人题库、本人使用追踪与准确版本跨卷统计；不含团队/公开题库、他人结果授权、跨版本合并或旧答案自动绑定。单卷仍显示份数，跨卷重复位置分别计回答条数，另列答卷份数和去重账号数。

启动器会核对第二阶段关键路径，已有旧版或其他服务占用8009时拒绝复用；请先停止该服务，再按需要备份升级并启动当前程序。Python依赖在requirements.txt锁定，可用`.\.venv\Scripts\python.exe -m pip check`检查。完整测试中的T43/T44/T46使用已有Node.js检查错误边界、取消返回及异步切换；Node缺失时明确跳过相应项，不能声称前端专项已验证，不需为运行应用安装Node。

重新交付前先更新报告PDF，并将本轮验证结果和最终文件SHA256写入测试证据。运行`.\.venv\Scripts\python.exe -X utf8 scripts/package-delivery.py`从白名单打包；它检查源码/报告哈希、ZIP内容、必要历史引用和解压文档链接，再替换最终ZIP。白名单仅收录应用、脚本、测试、文档证据和两份指定PDF，不收环境、数据库、备份、缓存或其他临时输出。报告PDF生成依赖属于文档工具，不加入系统运行依赖。


## 手动验收先走一条主线

先保存要保留的当前草稿再刷新网页，使用本次独立命名的数据。无需一开始反复切换账号并准备多份统计样本。

1. 顶部“题目中心”→“我的题目”→“打开题目”，在“当前准确版本”选择一个年龄题版本。“内容与版本”直接显示题干和校验；管理名称只方便自己找题。低频的恢复操作在内容区“更多”中，只在同系列新增一版。
2. 新建一份“手动简版验收”问卷，点“添加题目”→“我的题目”→“选择版本”→加入刚才那版→“完成”，保存并发布。此步不重复放题、不配置跳转。
3. 通过填写链接填20，到确认页后明确提交。先检查这份问卷的统计：有效1份、平均20；暂不核对包含其他历史问卷的默认跨卷总数。
4. 确认这条路线顺畅后，再分别做版本换版或共享撤销。精确的重复位置三计数样本属于测试记录中的统计专项，作为选做复核，不是入门操作的必要准备。

“另存为可复用题目”的取消会明确提示未创建题目；确认后才保存问卷草稿并另存。问卷题目点击摘要展开编辑，一次展开一题；“更多”中提供移动、移除、另存和复用位置换版。选择已有题目的弹窗只有点击加入/换版时才保存，直接关闭不保存未完成编辑。由题目版本进入“加入题库”，加入或取消后返回原准确版本与页签；题库列表内直接加题本轮未增加。

本次交付另做了独立目录、全新虚拟环境与空库验证：锁定依赖安装和检查通过，10项冒烟/启动及前端检查通过，实际网页完成注册至提交统计。验证范围和环境限制见[测试记录O批](docs/测试记录.md)；不能据此保证任意系统、旧浏览器或受限网络环境均可运行。
