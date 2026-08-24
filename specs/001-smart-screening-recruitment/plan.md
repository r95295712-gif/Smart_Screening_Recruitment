# 智筛招聘一期技术方案

## 1. 方案状态

- 功能编号：001
- 状态：已批准实施
- 创建日期：2026-08-08
- 依据：`spec.md`、项目章程和项目设定记录

## 2. 技术目标

构建一个模块化 Django 单体应用，以最少的部署组件完成一期核心流程，并保留后续拆分服务的边界。开发环境允许使用 SQLite、本地文件存储和 Celery eager 模式；生产环境使用 PostgreSQL、Redis、MinIO/S3 兼容存储和独立 Celery worker。

## 3. 技术栈

### 应用

- Python 3.13
- Django 5.2 LTS
- Celery 5.6
- Redis 作为生产任务队列
- PostgreSQL 作为生产数据库
- Django Templates + 原生 JavaScript + 项目内 CSS

### 文件与解析

- Django Storage API
- MinIO/S3 兼容对象存储
- `python-docx` 解析 DOCX
- PyMuPDF 解析 PDF
- Tesseract OCR 作为可选外部能力

### 外部集成

- `httpx` 调用北森 API
- OpenAI-compatible API 客户端调用已批准模型
- Django 邮件后端发送负责人审核邮件

### 部署

- Docker Compose
- Web、Worker、PostgreSQL、Redis、MinIO 六个生产组件
- Nginx/企业网关负责 HTTPS、内网/VPN 和公网审核路由

## 4. 架构边界

### `accounts`

- 自定义用户、角色、密码强制修改、登录失败锁定、会话失效。
- 管理员用户管理和临时密码重置。

### `recruitment`

- 候选人、岗位、投递、简历版本、同步任务、排除标识、通知和审计。
- 北森 API 客户端、全量/增量同步和文件下载。
- 岗位列表、投递列表和候选人详情。

### `analysis`

- 系统提示词版本、模型版本、岗位规则版本。
- AI 分析批次、单项任务、报告和 HR 补充内容。
- PII 脱敏、提示词构建、模型调用、报告校验和复用。

### `reviews`

- 负责人、岗位负责人配对、审核批次、审核项和公开链接。
- 邮件发送、重试、链接过期、撤销和结果回写。

### `talent_pool`

- 人才库成员、团队标签、备注、移出恢复和推荐到岗位。

### `core`

- Django 项目配置、公共模板、仪表盘、健康检查和 Celery 初始化。

## 5. 数据模型

### 身份与权限

- `accounts.User`
  - username、role、must_change_password
  - failed_login_attempts、locked_until
  - session_version、is_active

### 招聘域

- `Position`
  - beisen_position_id、requisition_id、name、type
  - source_jd、evaluation_jd
  - status、status_source、manual_status_override、last_synced_at
- `Candidate`
  - applicant_id 唯一
  - 北森只读资料与原始 JSON
- `Application`
  - application_id 唯一，可为空仅用于人才库推荐
  - local_reference 唯一
  - candidate、position、source_type、status、applied_at
  - deleted_at、purge_after
- `ResumeVersion`
  - candidate、content_hash、source_type、source_file、standard_pdf
  - extracted_text、parse_status、parse_quality、created_at
- `SyncJob`
  - sync_type、window、cursor、status、统计和错误
- `ExclusionMarker`
  - application_id 唯一、created_at
- `AuditEvent`
  - actor、action、object_type、object_reference、metadata、created_at
- `Notification`
  - user、type、title、message、read_at

### AI 域

- `PromptVersion`
- `ModelVersion`
- `PositionRuleVersion`
  - position、version、status、evaluation_jd
  - hard_requirements、dimensions、bonus_items、rating_thresholds
- `AnalysisJob`
  - requested_by、position、status、总数和统计
- `AnalysisItem`
  - job、application、resume_version、rule_version、status、error
- `AnalysisReport`
  - item、prompt_version、model_version
  - score、rating、hard_requirement_results、dimension_results
  - strengths、risks、missing_information、interview_focus、questions
- `ReportNote`
  - report、author、note_type、content

### 审核域

- `Reviewer`
  - name、email、is_active
- `PositionReviewer`
  - position、reviewer
- `ReviewBatch`
  - reviewer、created_by、token_hash、expires_at、status、email_status
- `ReviewItem`
  - batch、application、decision、comment、submitted_at、draft

### 人才库域

- `TalentMembership`
  - candidate 唯一、status、joined_by、joined_at、removed_at、purge_after
- `TalentTag`
  - name、created_by、is_active
- `TalentTagAssignment`
- `CandidateNote`
  - candidate、author、scope、content

## 6. 关键一致性策略

1. 北森对象使用外部 ID 唯一约束和 `update_or_create` 保证幂等。
2. 人才库推荐使用本地引用，不伪造北森 `applicationId`。
3. AI 报告复用键为投递、简历版本、已发布规则版本和成功状态。
4. 规则、报告、简历和提示词只新增版本，不原地覆盖已被引用的版本。
5. 删除业务数据时先软删除；清理任务在 3 天后执行，并留下排除标识。
6. 审核链接只保存 Token 哈希，明文 Token 只在生成链接时使用。
7. 异步任务使用数据库状态和幂等键，Celery 只负责触发执行。

## 7. 北森集成方案

### 客户端

- 统一处理 Token 缓存、Authorization、超时、限流、重试和错误格式。
- 已知接口作为默认配置。
- 投递通用信息、职位和招聘需求接口通过环境变量覆盖，避免在未确认时写死。

### 全量同步

1. 创建 `SyncJob`。
2. 按时间窗口获取 `applicantId`。
3. 批量拉取个人资料和允许的简历模块。
4. 逐候选人或按正式接口能力拉取投递。
5. 幂等保存候选人、投递和岗位。
6. 对有效岗位简历创建文件下载任务。

### 增量与校准

- 增量按简历更新时间执行。
- 校准使用重叠窗口。
- 同一批次可安全重放。
- 排除标识在写入投递前检查。

## 8. 简历文件与解析

1. 原始文件作为正式文件，标准 PDF 作为预览。
2. 下载后计算 SHA-256。
3. PDF 和 DOCX 本地解析。
4. DOC 先标记需要转换，不伪装成功。
5. 扫描 PDF 在配置 OCR 后执行 OCR。
6. 提取文本过短或不可读时标记低质量。
7. 低质量和失败状态阻止正式 AI 评分。

## 9. AI 分析流程

1. HR 选择投递并创建分析批次。
2. 系统校验岗位有效、规则已发布、简历可解析。
3. 命中复用条件时关联现有报告。
4. 其他项进入 Celery。
5. 调用前执行 PII 脱敏。
6. 固定系统提示词、岗位规则和简历组成结构化请求。
7. 模型必须返回 JSON；服务层校验字段和分数范围。
8. 失败自动重试 3 次，仍失败保留错误。
9. 成功后保存不可变报告和版本引用。

## 10. 负责人审核流程

1. HR 根据岗位配置选择负责人。
2. 按负责人分组创建批次。
3. 生成高熵 Token，只保存哈希。
4. 邮件包含批次链接和过期时间。
5. 公网页面只返回允许字段和在线预览。
6. 负责人可保存草稿或提交结果。
7. 全部提交后批次失效。
8. 撤销、过期或删除投递时禁止继续访问。

## 11. 安全

- Django PBKDF2 密码哈希。
- CSRF、Secure Cookie、HttpOnly、SameSite 和 HTTPS 配置。
- 管理界面通过网关限制内网/VPN。
- 公网审核页使用独立路由、Token 哈希、过期和范围校验。
- 登录失败锁定在认证服务中执行。
- API Key、Secret 和初始管理员密码只来自环境变量。
- 模型请求和日志不保存不必要的 PII。
- 文件响应使用权限检查和短时读取，不暴露对象存储路径。

## 12. 可观测性

- Django 结构化日志输出到标准输出。
- 记录同步、分析、邮件和清理任务状态。
- 健康检查区分 Web、数据库、Redis 和对象存储。
- 管理员仪表盘显示失败任务和模型统计。
- 不引入复杂监控平台，预留日志采集接口。

## 13. 测试策略

### 单元测试

- 身份和唯一约束。
- 登录锁定与密码重置。
- 规则发布和版本。
- 报告复用、重新分析和评分校验。
- 审核链接生命周期和可见字段。
- 人才库入库、移出和推荐。
- 软删除、恢复、排除标识和清理。

### 集成测试

- 使用 Fake iTalent Client 验证全量和增量幂等。
- 使用 Fake Model Gateway 验证批量成功、部分失败和重试。
- 使用内存邮件后端验证分组邮件和重发。
- 使用 Django 测试客户端验证权限和主要页面。

### 系统验证

- `python manage.py check`
- `python manage.py makemigrations --check`
- `python manage.py test`
- `docker compose config`
- 外部凭据可用后执行独立联调脚本，不在普通测试中调用正式服务。

## 14. 部署与迁移

1. 开发默认 SQLite、本地媒体目录、内存邮件和 Celery eager。
2. 生产通过环境变量切换 PostgreSQL、Redis、MinIO 和 SMTP。
3. 容器启动执行数据库迁移和静态文件收集。
4. 初始管理员通过管理命令读取环境变量创建。
5. 每日备份由独立容器或平台定时任务执行。
6. 生产切换前先导入北森少量时间窗口验证，再执行全量。

## 15. 外部阻塞项

- 北森投递、职位和招聘需求正式接口与权限。
- 正式北森凭据。
- 岗位负责人配对。
- 模型与邮件凭据。
- 生产服务器、域名、VPN 和对象存储。

这些阻塞项不阻止本地 MVP、Fake 集成和适配器实现，但阻止宣称正式集成完成。

## 16. 章程复核

- 北森身份边界：覆盖。
- AI 人工决策边界：覆盖。
- 版本追溯：覆盖。
- 个人信息最小化：覆盖。
- 异步可靠性：覆盖。
- 权限：覆盖。
- 删除与备份：覆盖。
- 测试与验收分离：覆盖。
