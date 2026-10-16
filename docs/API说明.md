# API 使用说明

本文供接口调用者和测试者使用。**唯一接口字段契约是运行中应用的 [OpenAPI](http://127.0.0.1:8009/openapi.json)**，由 [models.py](../app/models.py) 和 [main.py](../app/main.py) 自动生成；可通过 [Swagger 页面](http://127.0.0.1:8009/docs) 查看。本文只说明使用顺序、权限和调用约定，不复制一套字段表。启动方法见 [README](../README.md)。

## 认证与请求约定

先 GET `/api/session`，保存服务端 Cookie 和返回的 `csrf`。所有写请求携带 `X-CSRF-Token: <csrf>` 和 Cookie；有 Origin 时须与访问服务的源相同。随后调用注册和登录。业务接口使用 HttpOnly 的 `survey_session` 会话 Cookie；12 小时有效，可退出失效。浏览器页面已自动处理这些步骤。

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

`/submit` 的 submissionKey 是一次用户提交尝试的幂等键：网络重试沿用相同键及完全相同内容，返回相同答卷的结果；主动新填一次生成新键。同一键改内容返回冲突。已成功请求的相同重试即使问卷随后关闭仍能取回原成功结果，不会新增答卷。每账号一次策略由 MongoDB 唯一索引兜底。anonymous=true 只有在问卷允许时生效；不允许匿名则按非匿名保存。

统计只返回展示所需数据；文本和数字回答中，非匿名可显示用户名，匿名只显示“匿名”，不会返回内部 respondentId、payloadHash、singleSubmissionKey。问卷全卷统计包含各题内容的第一页，更多内容使用单题分页接口。

## 错误与可复现示例

常见结果为 200 成功、201 创建成功、401 未登录或过期、403 CSRF/Origin 校验失败、404 不存在或无权访问、409 状态或版本冲突及重复填写、413 请求超过 2.5 MB、422 输入或业务校验失败。错误使用 `detail` 字段，不回显密码输入。

可执行调用顺序见 [tests/test_system.py](../tests/test_system.py) 的 Browser、create、publish、payload 辅助函数和测试；完整示例生成工具见 [scripts/demo.py](../scripts/demo.py)，通过正式 API 创建，不直接写业务集合。它不覆盖已有同名示例。
