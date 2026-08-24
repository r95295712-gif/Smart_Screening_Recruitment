# 智筛招聘一期实施任务

## 任务规则

- `[ ]` 未开始，`[~]` 进行中，`[x]` 已完成。
- 每项完成必须满足对应验证结果。
- 外部正式凭据缺失时，Fake 集成通过不等于正式集成完成。

## Phase 1：项目基础

- [x] **T001** 创建 Django 项目、应用目录、依赖文件和环境变量模板。  
  文件：`manage.py`、`config/`、`requirements/`、`.env.example`  
  验证：`python manage.py check`
- [x] **T002** 配置开发/生产数据库、存储、邮件、Celery 和日志。  
  文件：`config/settings/`、`config/celery.py`  
  依赖：T001  
  验证：开发配置启动；`docker compose config`
- [x] **T003** 创建 Dockerfile、Compose 和启动脚本。  
  文件：`Dockerfile`、`compose.yaml`、`docker/`  
  依赖：T001  
  验证：Compose 配置解析通过
- [x] **T004** 建立公共模板、CSS、导航、仪表盘和健康检查。  
  文件：`templates/`、`static/`、`core/`  
  依赖：T001  
  验证：匿名访问登录页；登录后访问仪表盘

## Phase 2：账号与权限

- [x] **T010** 实现自定义用户、HR/管理员角色和初始迁移。  
  文件：`accounts/models.py`、`accounts/migrations/`  
  依赖：T001  
  验证：角色和唯一账号测试通过
- [x] **T011** 实现登录锁定、会话限制、首次改密和退出。  
  文件：`accounts/backends.py`、`accounts/views.py`、`accounts/forms.py`  
  依赖：T010  
  验证：锁定、超时、首次改密测试通过
- [x] **T012** 实现管理员用户列表、创建、停用、解锁和临时密码重置。  
  文件：`accounts/admin_views.py`、`accounts/templates/`  
  依赖：T011  
  验证：管理员权限和会话失效测试通过
- [x] **T013** 实现初始管理员创建命令。  
  文件：`accounts/management/commands/bootstrap_admin.py`  
  依赖：T010  
  验证：缺少环境变量时安全失败；成功创建后要求改密

## Phase 3：招聘数据与北森同步

- [x] **T020** 实现岗位、候选人、投递、简历版本、同步、排除、审计和通知模型。  
  文件：`recruitment/models.py`、`recruitment/migrations/`  
  依赖：T010  
  验证：唯一约束和多岗位投递测试通过
- [x] **T021** 实现北森客户端、Token 缓存、限流、重试和错误模型。  
  文件：`recruitment/integrations/italent.py`  
  依赖：T020  
  验证：Fake HTTP 测试覆盖分页、认证失败和重试
- [x] **T022** 实现全量、增量和校准同步服务。  
  文件：`recruitment/services/sync.py`、`recruitment/tasks.py`  
  依赖：T021、T002  
  验证：重复同步不新增重复记录
- [x] **T023** 实现文件下载、摘要、版本和本地/S3 存储。  
  文件：`recruitment/services/files.py`  
  依赖：T020、T002  
  验证：相同文件复用、更新文件新增版本
- [x] **T024** 实现 PDF、DOCX 和 OCR 可选解析流程。  
  文件：`recruitment/services/parsing.py`、`recruitment/tasks.py`  
  依赖：T023  
  验证：成功、低质量和失败状态测试通过
- [x] **T025** 实现岗位、投递列表、搜索、筛选和候选人详情。  
  文件：`recruitment/views.py`、`recruitment/forms.py`、`recruitment/templates/`  
  依赖：T020、T004  
  验证：页面权限、搜索和多岗位显示测试通过
- [x] **T026** 实现原始简历下载和标准 PDF 在线预览权限。  
  文件：`recruitment/file_views.py`  
  依赖：T023、T025  
  验证：HR 可下载；匿名和负责人不能下载

## Phase 4：岗位规则与 AI 分析

- [x] **T030** 实现提示词、模型、岗位规则版本模型和管理界面。  
  文件：`analysis/models.py`、`analysis/views_rules.py`、`analysis/templates/`  
  依赖：T020、T004  
  验证：只有管理员可发布；历史版本不可改写
- [x] **T031** 实现 JD 差异和 AI 规则草稿服务接口。  
  文件：`analysis/services/rules.py`  
  依赖：T030  
  验证：无模型时明确失败；Fake 模型生成可编辑草稿
- [x] **T032** 实现 PII 脱敏、提示词构建和结构化报告校验。  
  文件：`analysis/services/redaction.py`、`analysis/services/prompts.py`、`analysis/services/schema.py`  
  依赖：T030  
  验证：敏感字段移除和错误报告拒绝测试通过
- [x] **T033** 实现模型网关和单项分析服务。  
  文件：`analysis/integrations/model.py`、`analysis/services/analyze.py`  
  依赖：T032  
  验证：Fake 模型成功、异常和重试测试通过
- [x] **T034** 实现分析批次、Celery 任务、复用和重新分析。  
  文件：`analysis/tasks.py`、`analysis/services/jobs.py`  
  依赖：T033、T002  
  验证：20 项批次、部分失败、复用和新版本测试通过
- [x] **T035** 实现分析选择、进度、报告详情、备注和导出。  
  文件：`analysis/views.py`、`analysis/templates/`、`analysis/exports.py`  
  依赖：T034、T025  
  验证：HR 页面、PDF/Excel 内容和权限测试通过
- [x] **T036** 实现管理员模型用量和预估费用视图。  
  文件：`analysis/views_admin.py`  
  依赖：T034  
  验证：HR 禁止访问，管理员可筛选统计

## Phase 5：负责人审核

- [x] **T040** 实现负责人、岗位配对、审核批次和审核项模型。  
  文件：`reviews/models.py`、`reviews/migrations/`  
  依赖：T020  
  验证：岗位负责人和批次唯一性测试通过
- [x] **T041** 实现按负责人分组送审、Token 哈希、有效期和撤销。  
  文件：`reviews/services.py`  
  依赖：T040  
  验证：分组、过期、完成和撤销测试通过
- [x] **T042** 实现邮件发送、重试和站内失败通知。  
  文件：`reviews/tasks.py`、`reviews/emails.py`、`reviews/templates/email/`  
  依赖：T041、T002  
  验证：内存邮件后端验证分组与重发
- [x] **T043** 实现公网审核页面、草稿、提交和最小可见范围。  
  文件：`reviews/public_views.py`、`reviews/templates/public/`  
  依赖：T041、T026  
  验证：匿名持有效 Token 可见允许字段；禁止下载和越权
- [x] **T044** 实现 HR 审核状态和删除撤回联动。  
  文件：`reviews/signals.py`、`reviews/views.py`  
  依赖：T043  
  验证：删除撤回、恢复不自动重开测试通过

## Phase 6：人才库与删除恢复

- [x] **T050** 实现人才库、团队标签和候选人备注模型。  
  文件：`talent_pool/models.py`、`talent_pool/migrations/`  
  依赖：T020  
  验证：候选人唯一成员、标签和备注权限测试通过
- [x] **T051** 实现人才库列表、搜索、筛选、入库和移出恢复。  
  文件：`talent_pool/views.py`、`talent_pool/templates/`  
  依赖：T050、T004  
  验证：结构化搜索、3 天恢复和非自动入库测试通过
- [x] **T052** 实现人才推荐到岗位及北森正式投递关联。  
  文件：`talent_pool/services.py`  
  依赖：T051、T022  
  验证：本地推荐、关联和新简历提醒测试通过
- [x] **T053** 实现投递软删除、回收站、永久清理和排除标识。  
  文件：`recruitment/services/deletion.py`、`recruitment/views_recycle.py`、`recruitment/tasks.py`  
  依赖：T020、T044  
  验证：立即隐藏、管理员恢复、3 天清理和同步排除测试通过

## Phase 7：集成、部署与验证

- [x] **T060** 实现站内通知中心和管理员任务状态仪表盘。  
  文件：`core/views.py`、`core/templates/`  
  依赖：T022、T034、T042  
  验证：通知已读和角色可见性测试通过
- [~] **T061** 实现每日备份脚本和恢复说明。  
  文件：`docker/backup/`、`docs/operations.md`  
  依赖：T003  
  验证：脚本 dry-run 和 7 个恢复点轮转测试
- [x] **T062** 完成 Fake iTalent、Fake Model 和测试样本。  
  文件：`tests/fakes/`、`tests/fixtures/`  
  依赖：T021、T033  
  验证：测试不访问正式外部服务
- [x] **T063** 运行全量测试和 Django 系统检查，修复失败。  
  依赖：T001–T062  
  验证：`python manage.py check`、`python manage.py makemigrations --check`、`python manage.py test`
- [x] **T064** 更新测试结果、外部未验证项和部署说明。  
  文件：`docs/test-results.md`、`docs/operations.md`、`docs/项目设定记录.md`  
  依赖：T063  
  验证：只记录实际结果，不宣称用户验收通过
- [x] **T065** 接入北森正式投递与职位接口并准备外部服务配置。  
  文件：`recruitment/integrations/italent.py`、`recruitment/services/sync.py`、`.env.example`、`docs/`  
  依赖：T064  
  验证：Fake 请求结构和项目检查通过；正式 Token、候选人、投递、职位、简历文件及项目原生网络链路联调通过
- [x] **T066** 修复北森真实动态字段、投递扩展字段和文件下载处理。  
  文件：`recruitment/integrations/italent_fields.py`、`recruitment/integrations/italent.py`、`recruitment/services/sync.py`、`config/settings/base.py`  
  依赖：T065  
  验证：正式最近 7 天同步成功，61 条投递均有时间和渠道，61 份简历解析与预览成功，敏感签名 URL 不进入 INFO 日志
- [x] **T067** 核对正式同步数据与本地简历文件一致性。  
  文件：`media/resumes/`、`docs/test-results.md`、`docs/operations.md`、`docs/项目设定记录.md`  
  依赖：T066  
  验证：122 个数据库文件引用对应 122 个磁盘文件，无缺失、无孤立；36 项测试、系统检查和迁移检查通过
- [x] **T068** 兼容北森历史资料中的非严格 JSON 控制字符并显示任务级错误。  
  文件：`recruitment/integrations/italent.py`、`templates/recruitment/sync_jobs.html`、`tests/test_workflows.py`、`docs/`  
  依赖：T067  
  验证：全量 1508 个候选人只读遍历、192 次批量接口调用失败 0；38 项测试通过
- [x] **T069** 使用北森标准 PDF 修复图片和低文本质量简历解析。  
  文件：`recruitment/services/parsing.py`、`tests/test_workflows.py`、`docs/`  
  依赖：T068  
  验证：全量任务 11 份问题简历全部修复，1453 份简历解析成功；47 项测试通过
- [x] **T070** 检查特殊数据并修复招聘渠道显示。  
  文件：`recruitment/services/sync.py`、`tests/test_workflows.py`、`docs/special-data-check.md`、`docs/hr-input-template.md`  
  依赖：T069  
  验证：全量数据无重复记录，1455 条渠道转换为可读名称；删除重同步排除、无联系方式页面和渠道字典回归测试通过；47 项测试通过
- [x] **T071** 向 HR 开放同步任务和历史简历按需补拉。  
  文件：`recruitment/views.py`、`recruitment/tasks.py`、`recruitment/urls.py`、`templates/`、`tests/test_workflows.py`、`docs/`  
  依赖：T070  
  验证：HR 可查看和发起同步；缺失简历可后台下载、解析、关联并发送成功或失败通知；47 项测试通过
