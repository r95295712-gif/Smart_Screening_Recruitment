# 智筛招聘

基于 Django、Celery、PostgreSQL、Redis 和 MinIO 的招聘简历同步、AI 辅助分析、负责人审核与人才库系统。

## 本地启动

项目入口会自动读取根目录 `.env`，已存在的系统环境变量优先，不会被文件中的值覆盖。

```text
python -m venv .venv
.venv\Scripts\pip install -r requirements\dev.txt
.venv\Scripts\python manage.py migrate
.venv\Scripts\python manage.py bootstrap_admin
.venv\Scripts\python manage.py runserver
```

运行 `bootstrap_admin` 前需要设置 `BOOTSTRAP_ADMIN_PASSWORD`。开发环境默认使用 SQLite、本地文件、内存邮件和 Celery eager。

## 验证

```text
.venv\Scripts\python manage.py check
.venv\Scripts\python manage.py makemigrations --check
.venv\Scripts\python manage.py test
docker compose --env-file .env.example config
```

用户可读的系统规则见 `docs/用户业务规则说明.md`。生产配置与外部凭据说明见 `docs/operations.md`，实际测试结果和未验证项见 `docs/test-results.md`。
