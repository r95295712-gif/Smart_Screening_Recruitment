# 智筛招聘部署与运维

## 1. 部署模式与网络说明

项目支持两种部署模式：
1. **内部直连模式（直接暴露 8000 端口）**：
   - 内部人员在局域网内直接访问 `http://<SERVER_IP>:8000`。
   - `DJANGO_ALLOWED_HOSTS` 必须填写服务器 IP（如 `192.168.1.100,localhost,127.0.0.1`）。
   - `DJANGO_CSRF_TRUSTED_ORIGINS` 必须填写完整地址与端口（如 `http://192.168.1.100:8000`），否则表单提交将报 403 CSRF 错误。
   - `PUBLIC_REVIEW_BASE_URL` 设置为 `http://<SERVER_IP>:8000`，确保负责人（Reviewer）在同一内网或 VPN 下可打开审核页面。
2. **反向代理模式（Nginx / HTTPS 域名网关）**：
   - 由 Nginx 提供 HTTPS 证书并在公网开放 `/reviews/public/` 路径，管理后台限制内网 IP。
   - `SECURE_SSL_REDIRECT=true`，`DJANGO_CSRF_TRUSTED_ORIGINS=https://your-domain.com`。

## 2. 首次启动与部署预检

1. 复制 `.env.example` 为 `.env`，设置 `DJANGO_SECRET_KEY`、`POSTGRES_PASSWORD`、MinIO、SMTP、北森和模型配置。
2. 运行部署预检命令排查配置与网络连通性：
   ```bash
   # 本地或容器内执行一键环境自检
   docker compose run --rm web python manage.py check_deployment
   # 或跳过外部三方接口测试
   docker compose run --rm web python manage.py check_deployment --skip-external
   ```
3. 镜像内置 `docs/招聘信息汇总.docx`。首次启动 Web 容器时，入口脚本会在创建初始管理员后自动将该文档解析并发布为 V1 初始参考资料；重复启动不会重复导入。可通过 `SEED_INITIAL_REFERENCE=false` 关闭。
4. 启动服务集群：
   ```bash
   docker compose build
   docker compose up -d
   ```
5. 检查各容器健康状态：
   ```bash
   docker compose ps
   ```
   所有服务 (`web`, `worker`, `beat`, `db`, `redis`, `minio`) 状态应为 `healthy` 或 `running`。

## 3. 同步计划与任务处理

- HR 和管理员都可以在“同步任务”页面查看并手动发起同步；操作会记录发起人和审计事件。
- 新岗位规则 V0 生成是同步完成后派发的独立 Celery 子任务，不计入北森同步进度、同步失败数或同步最终状态；同步列表单独展示等待、生成中、完成和失败数量。
- 规则 V0 生成失败时不会回滚已同步的候选人、投递、岗位或简历数据。HR 会收到站内通知，并可在“岗位初始化任务”页面单独重新生成。
- 候选人、投递和简历：默认每 10 分钟增量同步。
- 岗位与 JD：默认每小时同步。
- 校准：每天使用最近 7 天重叠窗口执行一次。
- 已配置正式投递接口 `Apply/GetApplyListByApplicantId` 和职位接口 `Job/GetJobListByIds`；未提供连接器凭据时只能运行 Fake 集成测试。
- 投递接口请求必须携带 `ITALENT_APPLICATION_FIELDS`；默认字段包含首次/归属/最后投递时间、渠道、媒介、创建时间、状态和招聘需求 ID。
- 北森返回的不带时区投递时间按系统时区 `Asia/Shanghai` 保存。
- 一期不使用岗位类型；正式职位接口返回的 `jobType/category/kind` 不参与业务展示、筛选或规则判断。
- 北森授权 IP 必须填写调用方的公网出口 IP；生产环境通常是服务器或 NAT 网关的固定公网 IP。
- 本机直接调用北森进行联调时，也需临时授权本机所在网络的公网出口 IP；`127.0.0.1`、`192.168.x.x` 和 `10.x.x.x` 等地址不能作为公网授权 IP。
- 当前开发联调通过 WireGuard 分流，仅将北森 OpenAPI 流量转发至腾讯云固定出口 `122.51.104.159`；该地址需要加入北森 OpenAPI 受信 IP。
- Clash Verge 使用 Fake-IP/TUN 时，需要将 `openapi.italent.cn` 加入 `fake-ip-filter`，并创建 `type: direct`、`interface-name: wg-windows` 的专用出口，将北森域名规则指向该出口。仅设置 `DOMAIN,openapi.italent.cn,DIRECT` 会使用 Clash 自身选择的本地出口，不能保证经过 WireGuard。
- `httpx` 和 `httpcore` 的生产/开发日志默认设为 `WARNING`，避免终端记录简历临时签名 URL；排查网络问题时也不要直接开启完整 URL 的 INFO 日志。
- 历史岗位缺失简历不会在全量同步时自动下载；HR 或管理员可在投递列表按需发起后台补拉，结果通过站内通知反馈。
- 本地联调可设置 `LOCAL_BACKGROUND_TASKS=true`，使 AI 分析、北森同步、简历补拉和送审邮件使用进程内后台线程，避免页面请求长时间等待；该方式只用于单机测试，关闭开发服务器会中断尚未完成的任务。
- 生产环境必须设置 `LOCAL_BACKGROUND_TASKS=false`，并运行 Redis 和 Celery Worker，不得依赖进程内后台线程。

## 4. 模型配置

- 模型网关使用 `MODEL_BASE_URL=https://ai.libibi.top/v1`。
- API Key 填入 `.env` 的 `MODEL_API_KEY`，不要提交到代码仓库。
- 当前配置 `MODEL_NAME=gpt-5.6-sol`，用于强调分析质量的简历与 JD 长文本判断。
- 2026-08-10 已通过网关 `/v1/models` 和最小 JSON 对话请求确认该模型可用；系统不会静默切换模型。

## 5. 邮箱配置

- 需要在发件邮箱或企业邮箱后台开通 SMTP。
- `EMAIL_HOST_PASSWORD` 通常填写 SMTP 授权码或应用专用密码，不填写网页登录密码。
- 587 端口通常设置 `EMAIL_USE_TLS=true`、`EMAIL_USE_SSL=false`。
- 465 端口通常设置 `EMAIL_USE_TLS=false`、`EMAIL_USE_SSL=true`。
- 本地开发默认使用内存邮件后端；需要真实发信时，将 `EMAIL_BACKEND` 改为 `django.core.mail.backends.smtp.EmailBackend`。
- 还需填写 `EMAIL_HOST`、`EMAIL_PORT`、`EMAIL_HOST_USER`、`DEFAULT_FROM_EMAIL` 和 `PUBLIC_REVIEW_BASE_URL`。

## 6. 备份与恢复

`docker/backup/backup.sh` 使用 `pg_dump`、gzip 和 AES-256-CBC 加密数据库备份，并只保留最近 7 个每日恢复点。

```text
docker compose --profile operations run --rm backup --dry-run
docker compose --profile operations run --rm backup
```

生产环境需要由平台定时任务每日执行，并把 `/backups` 放在独立加密存储。MinIO 对象数据应使用存储平台的版本化/快照能力执行同频备份。

### 整体恢复流程
1. 停止 Web、Worker 和 Beat。
2. 准备同版本代码、环境变量和对象存储快照。
3. 使用 `openssl enc -d -aes-256-cbc -pbkdf2` 解密备份，再经 `gunzip` 和 `psql` 恢复整个数据库。
4. 恢复同时间点的 MinIO 快照。
5. 启动服务，执行 `python manage.py check_deployment` 健康检查和抽样核对。

## 7. 常见上线故障排查 (FAQ)

1. **登录或提交表单报 `403 Forbidden (CSRF verification failed)`**
   - **原因**：通过 IP+端口访问时，未将访问来源加入 `DJANGO_CSRF_TRUSTED_ORIGINS`。
   - **解决**：在 `.env` 中添加 `DJANGO_CSRF_TRUSTED_ORIGINS=http://<SERVER_IP>:8000` 并重启 Web 容器。
2. **页面出现重定向循环或无法连接 (SSL Connection Error)**
   - **原因**：在无 SSL 证书的纯 HTTP 端口环境下开启了 `SECURE_SSL_REDIRECT=true`。
   - **解决**：在 `.env` 中设置 `SECURE_SSL_REDIRECT=false`。
3. **MinIO 容器启动报错或重启**
   - **原因**：`AWS_SECRET_ACCESS_KEY` 长度不足 8 字符，或 `AWS_ACCESS_KEY_ID` 长度不足 3 字符。
   - **解决**：在 `.env` 中设置合规的访问密钥（如 `AWS_SECRET_ACCESS_KEY=minioadmin123`）。

