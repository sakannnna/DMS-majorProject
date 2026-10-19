# API 使用说明

API是页面与服务端交换数据的入口：例如网页点击“发布”，会发出带问卷编号和编辑版本的请求；服务端返回最新问卷或明确的错误。本文先给调用顺序和完整示例，再列准确的输入输出约定，供用户理解流程，也供开发者检查调用。

字段类型、必填性由[请求模型](../app/models.py)、[输出模型](../app/contracts.py)与[路由](../app/main.py)生成[OpenAPI](http://127.0.0.1:8009/openapi.json)，可在[交互页面](http://127.0.0.1:8009/docs)逐项查询。本文是这些契约的可读说明，不另存一套JSON schema；下文已解释主要输入、输出与空值，阅读时不必先翻代码。须先按[README](../README.md)启动服务。

## 认证与请求约定

Cookie用于把后续请求关联到同一浏览器；csrf是写操作需要附带的校验值。先 GET `/api/session`，保存服务端 Cookie 和返回的 `csrf`。所有写请求携带 `X-CSRF-Token: <csrf>` 和 Cookie；有 Origin 时须与访问服务的源相同。随后调用注册和登录。业务接口使用 HttpOnly 的 `survey_session` 会话 Cookie；12 小时有效，可退出失效。浏览器页面已自动处理这些步骤。

注册使用用户名与至少 8 位密码，注册成功后再登录。用户名经过 NFKC、首尾去空白和大小写规范化去重。测试或调用程序不要将密码、会话 Cookie 写进日志。

接口均以 JSON 通信。文本和数字答案使用字符串，多选为选项标识数组；未答的选填题显式使用 null 或空值，不能直接漏掉已到达题目。数字以字符串传入防止客户端浮点精度丢失，存储为 Decimal128，响应中数字均以十进制字符串表示。日期需带时区，例如 `2026-10-20T18:00:00+08:00`；空截止使用 null。对象标识对外为字符串，业务引用和规则目标使用稳定标识，不使用题号。

## 调用顺序

| 操作组 | 路径及用途 | 权限 |
| --- | --- | --- |
| 账号 | GET `/api/session`；POST `/api/register`、`/api/login`、`/api/logout` | 注册和登录不要求已有会话，但写操作仍需 CSRF |
| 我的问卷 | GET/POST `/api/surveys`；GET/PUT `/api/surveys/{survey_id}` | 已登录；管理读取和修改限创建者；PUT 只接受草稿 |
| 生命周期 | PATCH `/api/surveys/{survey_id}/metadata`；POST `…/publish`、`…/close` | 创建者；更新需当前 editRevision；关闭后无法重新发布 |
| 草稿预览 | POST `/api/surveys/{survey_id}/preview` | 创建者；返回问卷展示数据与遍历结果，绝不写答卷 |
| 填写 | GET `/api/fill/{token}`；POST `…/walk`、`…/submit` | 所有填写者均须登录；问卷需开放；提交还检查次数 |
| 统计 | GET `/api/surveys/{survey_id}/stats`、`…/questions/{question_id}/stats` | 仅创建者；单题内容支持 skip、limit 分页 |

创建草稿后，通过 PUT 完整保存题目、选项、校验和规则；发布前检查完整定义。修改时提供最近读取的 editRevision，冲突后重新读取，不强行覆盖。发布后只允许 metadata 接口更新标题、说明和截止，题目与匿名、重复设置被冻结；metadata 模型拒绝额外字段。已关闭问卷即使改截止也不会重开。

填写时按 `/walk` 返回的 nextQuestionId 显示下一题。ready=true 表示“进入提交确认”，不表示已保存；END 与自然结束均如此。确认后再调用 `/submit`，它会重新校验身份、状态、截止和完整路径。客户端不能绕过 `/walk` 的界面逻辑直接提交错误答案；后端会独立重放路径并拒绝未知、重复或路径外的答案。

`/submit` 的 submissionKey 是一次用户提交尝试的幂等键（例如点提交后网络超时，再发一次也只保存一份）：网络重试沿用相同键及完全相同内容，返回相同答卷的结果；主动新填一次生成新键。同一键改内容返回冲突。已成功请求的相同重试即使问卷随后关闭仍能取回原成功结果，不会新增答卷。每账号一次策略由 MongoDB 唯一索引兜底。anonymous=true 只有在问卷允许时生效；不允许匿名则按非匿名保存。

统计只返回展示所需数据；文本和数字回答中，非匿名可显示用户名，匿名只显示“匿名”，不会返回内部 respondentId、payloadHash、singleSubmissionKey。问卷全卷统计包含各题内容的第一页，更多内容使用单题分页接口。

## 主要请求输入

表中JSON字段名对应实际请求。POST/PUT/PATCH发送JSON对象，GET的分页参数放在URL查询串。请求不接受模型之外的额外字段，以免调用者误以为某项配置已保存。

| 操作 | 输入及业务含义 |
| --- | --- |
| 注册、登录 | username、password；注册成功不等于已登录，仍需调用login |
| 创建草稿 | title必填；description默认空、allowAnonymous默认true、allowMultiple默认false、deadline默认null、questions默认空数组；空草稿可保存但不能发布 |
| 完整保存草稿PUT | 上述定义及当前editRevision；它是整份替换，不能只传某一题假定其他内容自动保留 |
| 修改元信息PATCH | title、editRevision必填；description默认空、deadline默认null；应从当前问卷取值后修改，省略后两项会清空它们，不是“保持原值” |
| 发布、关闭 | editRevision；提供最近读取或保存后返回的版本号，避免旧页面覆盖新状态 |
| 遍历walk、预览preview | answers数组，元素含questionId、value；value为单选标识、多个标识的数组、文本/数字字符串，或显式空答null；可传部分已答内容计算下一题 |
| 提交submit | 完整有效路径的answers、submissionKey（8～80位字母/数字/下划线/短横线）、anonymous（默认true）；未到达题目不能混入，已到达的选填题应显式空答 |
| 列表、内容分页 | skip为从0开始跳过的条数；列表与单题内容limit均默认20、上限100（网页问卷列表主动使用12）；skip不为负，limit至少1 |

题目及校验字段在后面的“输出契约”统一说明；输入可省略默认的空options/jumpRules和未设限制。数字上下限也需能够精确存储，不能只校验填写答案。

## 完整示例：创建、确认提交、查看结果

以下是供调用者执行的示例。命令已在临时8011服务及独立测试库实跑核对，完成后清理；这属于文档示例验证，不计入已有74项全量测试。下列JSON用于说明契约，标识值为示意。需本机服务已启动；它会注册一个随机示例账号并留下问卷、答卷。为缩短操作，使用允许的“创建者自填”流程；两账号权限流程见测试记录T25。示例密码仅用于临时演示，不使用个人真实密码。

在PowerShell中整段执行。会话对象自动保存Cookie；请求JSON转为UTF-8字节，兼容Windows PowerShell中文输入。`$draft.id`用于管理，`$draft.token`用于分享填写，它们不能互换。

```powershell
$base = 'http://127.0.0.1:8009'
$web = New-Object Microsoft.PowerShell.Commands.WebRequestSession
$session = Invoke-RestMethod "$base/api/session" -WebSession $web
$headers = @{ 'X-CSRF-Token' = $session.csrf }
function Write-Api($method, $path, $data) {
    $json = $data | ConvertTo-Json -Depth 20 -Compress
    Invoke-RestMethod "$base$path" -Method $method -WebSession $web -Headers $headers -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($json))
}
$credentials = @{ username = ('api_' + [guid]::NewGuid().ToString('N').Substring(0,12)); password = 'example-only-123' }
$null = Write-Api 'POST' '/api/register' $credentials
$null = Write-Api 'POST' '/api/login' $credentials
$draft = Write-Api 'POST' '/api/surveys' @{
    title = '课程体验'; description = '接口演示'; allowAnonymous = $true; allowMultiple = $false
    questions = @(@{
        id = 'q1'; kind = 'single'; title = '是否满意？'; required = $true
        options = @(@{id='a'; label='满意'}, @{id='b'; label='待改进'})
    })
}
$published = Write-Api 'POST' "/api/surveys/$($draft.id)/publish" @{editRevision=$draft.editRevision}
$fill = Invoke-RestMethod "$base/api/fill/$($draft.token)" -WebSession $web
$answers = @(@{questionId='q1'; value='a'})
$confirmation = Write-Api 'POST' "/api/fill/$($draft.token)/walk" @{answers=$answers}
$confirmation | ConvertTo-Json -Depth 10
# 此处ready=true仅表示可确认，还没有答卷。以下调用代表用户明确确认提交。
$body = @{answers=$answers; submissionKey=[guid]::NewGuid().ToString('N'); anonymous=$true}
$saved = Write-Api 'POST' "/api/fill/$($draft.token)/submit" $body
$saved | ConvertTo-Json -Depth 10
$retry = Write-Api 'POST' "/api/fill/$($draft.token)/submit" $body
$retry | ConvertTo-Json -Depth 10
$stats = Invoke-RestMethod "$base/api/surveys/$($draft.id)/stats" -WebSession $web
$stats | ConvertTo-Json -Depth 10
$null = Write-Api 'POST' '/api/logout' @{}
```

该单题问卷自然结束时，walk完整预期响应为：

```json
{"path":["q1"],"nextQuestionId":null,"ready":true}
```

第一次submit的完整响应如下；responseId是服务端生成的示例编号，实际运行不同。相同body重试返回相同responseId，replayed变为true，message仍为“提交成功”；不能生成新键后把它称为同次网络重试。

```json
{"message":"提交成功","responseId":"507f1f77bcf86cd799439011","replayed":false}
```

统计完整预期响应如下。total=1表示已保存一份，respondentCount=1表示一个填写账号；q1的answered=1表示这一题有效回答一份。未被选择的b仍返回零计数，不能据此省略该选项。

```json
{
  "total":1,
  "respondentCount":1,
  "questions":[{
    "questionId":"q1","title":"是否满意？","kind":"single",
    "answered":1,"respondentCount":1,
    "options":[
      {"id":"a","label":"满意","count":1,"respondentCount":1},
      {"id":"b","label":"待改进","count":0,"respondentCount":0}
    ]
  }]
}
```

再如有数字题q2，读取 `/api/surveys/{id}/questions/q2/stats?skip=20&limit=20` 表示跳过前20条再取至多20条；answered与respondentCount仍是整题总数，不是这一页条数。hasMore=false表示这次查询时已到末页；平均值也是整题有效答卷平均。各页之间有新提交时不承诺固定快照。

## 如何理解错误

| 状态 | 含义及处理 |
| --- | --- |
| 200 / 201 | 请求成功 / 草稿或账号创建成功；walk的200不代表已提交 |
| 401 | 未登录或会话过期，重新登录 |
| 403 | CSRF或Origin校验失败，检查Cookie、校验头和访问源 |
| 404 | 不存在或当前账号无管理权限，不以不同错误泄露他人问卷 |
| 409 | 状态、编辑版本或重复填写冲突，读取最新状态；不得盲目更换提交键绕过限制 |
| 413 | 请求超过2.5 MB限制，缩小内容 |
| 422 | 输入结构或业务规则不合法，修正具体字段；创建者配置范围错误也属于此类 |

例如同一个submissionKey更改anonymous或答案后重交，返回409及完整错误对象：

```json
{"detail":"同一提交键不能用于不同内容"}
```

创建/保存草稿时，minimum和maximum指数或精度超出Decimal128支持范围返回422，detail提示支持范围。失败创建不新增文档，失败更新保留原内容和版本号；null表示未设上下限。JSON结构错误的detail可能是数组，形状在下节说明，不能把所有错误当字符串。

可复跑的数据准备工具为[scripts/demo.py](../scripts/demo.py)，通过正式接口创建且不覆盖已有同名示例；自动测试完整执行细节在[tests/test_system.py](../tests/test_system.py)。上面的示例已包含独立调用所需的准备，不要求先读这两个脚本。

## 输出契约

以下字段除显式说明外均必定返回；null是有意的空值，不等于缺字段。所有标识是字符串，时间是带时区的ISO字符串。数字题的数值字符串与计数整数不能混用。输出模型过滤新增的顶层内部存储字段；问题和选项结构复用现有请求模型，不保证任意新版嵌套结构可被旧程序读取。

| 接口 | 成功结构 | 空值和省略规则 |
| --- | --- | --- |
| GET /api/session | SessionOut：user、csrf；user包含id和username | 未登录user=null，csrf仍存在 |
| POST /api/register、/api/logout | MessageOut：message | 注册201，退出200 |
| POST /api/login | LoginOut：username，并设置会话Cookie | 没有user或message字段；前端随后重新获取session |
| GET /api/surveys | SurveySummaryOut数组 | 无问卷为[]，没有总数包装；刻意不含questions |
| POST /api/surveys；GET/PUT /api/surveys/{id}；PATCH metadata；POST publish/close | SurveyOut：完整管理问卷 | 创建201，其余200；均含questions，写入结果含最新editRevision |
| GET /api/fill/{token} | FillOut：title、description、questions、allowAnonymous、allowMultiple、deadline、definitionVersion | deadline可null；无管理id、ownerId、token、status、editRevision |
| POST /api/fill/{token}/walk | WalkOut：path、nextQuestionId、ready | path按访问顺序；待答时包含当前题；ready=true时nextQuestionId=null，不表示已保存 |
| POST /api/surveys/{id}/preview | PreviewOut：survey与walk | walk同上；survey仅含title、description、questions、allowAnonymous、allowMultiple，不含deadline和definitionVersion |
| POST /api/fill/{token}/submit | SubmitOut：message、responseId、replayed | 新保存replayed=false，取回原结果true；成功均200 |
| GET /api/surveys/{id}/stats | StatsOut：total、respondentCount、questions | total为份数整数，respondentCount为去重账号数整数；questions为单题统计数组 |
| GET /api/surveys/{id}/questions/{qid}/stats | 单个QuestionStatsOut | 与整卷questions元素相同，不再包装questions或total |

管理问卷的公共部分 SurveySummaryOut 为：id、ownerId、token、title、description、deadline、allowAnonymous、allowMultiple、status、editRevision、definitionVersion、schemaVersion、createdAt、updatedAt。SurveyOut在此基础上增加questions。deadline为null表示不限；status为draft/published/closed；description为空时返回空字符串。

题目结构为id、kind、title、required、options、validation、jumpRules。kind为single/multiple/text/number；无选项或规则时返回[]。选项含id和label。validation始终包含minChoices、maxChoices、minLength、maxLength、minimum、maximum、integer；未设置的上下限返回null，integer返回布尔值。minimum和maximum非空时是十进制字符串。规则含conditions和target；条件含op和value，value为字符串或字符串数组，target为稳定题目标识或END。完整约束以模型为准。

| 单题kind | 公共字段之外必定返回 | 不返回或为空 |
| --- | --- | --- |
| single、multiple | options数组，各项id、label、count、respondentCount | 不返回contents、average或分页字段；零次选项仍返回count=0、respondentCount=0 |
| text | contents、skip、limit、hasMore | 无回答contents=[]；不返回options或average |
| number | 同text，另有average | 无有效数值average=null；否则十进制字符串；不返回options |

单题公共字段为questionId、title、kind、answered、respondentCount。answered为有效回答份数，respondentCount为该题有效回答的去重账号数，均为整数；选择题选项count为选择份数，respondentCount为该选项去重账号数。contents每项仅含value、author、submittedAt；value为文本或数字字符串；author为用户名或“匿名”，不携带内部账号标识。分页的skip、limit为整数，hasMore为布尔值；整卷每题默认返回第一页20项，下一页调用单题接口。统计计数的业务口径只在[需求与设计](需求与设计.md)维护。

业务错误的detail为字符串；请求结构校验错误为detail数组，每项loc是字符串或整数数组、msg为字符串，不返回input。统一错误模型为ErrorOut，路由登记401/403/404/409/413/422结构，不表示每个路径都会产生所有状态。前端不应假定detail只有一种类型。

## 前端字段核对

对照[页面脚本](../app/static/app.js)逐项检查，当前字段匹配；覆盖自动检查见[测试记录](测试记录.md)T19。本表说明消费位置及容易破坏的约定，不重复维护字段类型。

| 消费位置 | 使用的输出 | 需要保持的约定 |
| --- | --- | --- |
| api、boot、account | ErrorOut、SessionOut | 错误兼容字符串和数组；user先判断null；csrf用于后续写请求 |
| list、renderEditor、collect、save | SurveySummaryOut、SurveyOut及嵌套题目 | 列表不读questions；编辑只使用完整问卷；写操作后使用返回的最新版本；选择题options及规则数组始终存在 |
| startFill、renderFill、constraintText、answerText | FillOut或PreviewOut.survey、Question | 两种survey共同部分可用于渲染，预览不得读取deadline或definitionVersion；validation未设值用null默认处理 |
| nextAnswer、revise | WalkOut或PreviewOut.walk | preview多一层walk包装；nextQuestionId=null进入确认，path用于返回修改；不将ready当成保存成功 |
| submit-answer | SubmitOut | 当前页面只依据HTTP成功展示提交成功，不读取message或responseId；这些字段仍供调用者和重试使用 |
| statistics、contents、content-page | StatsOut及按kind区分的QuestionStatsOut | 整卷与单题显示份数及respondentCount账号数，选项同时读取count和respondentCount；选择题依赖存在options；其他题依赖contents与分页；仅数字显示average；单题分页响应不带外层questions |

响应模型的校验和OpenAPI机制见[FastAPI官方说明](https://fastapi.tiangolo.com/tutorial/response-model/)。直接构造JSONResponse的账号接口也显式通过输出模型，再设置Cookie；其余接口通过response_model验证和过滤。
