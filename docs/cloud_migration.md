# 上云迁移清单（云上必做 · 本地未做）

> 本清单收纳**只在云上需要、本地无关或本地不能做的事**。每条注明：
> 为什么本地不做、影响范围、上云时怎么改。

---

## 限流后端切 Redis（影响：4 个密码接口）

**触发**：W7 Day2 加滑动窗口限流，但用的是 `app/services/rate_limit.py` 的内存 dict。
云上 `diag-backend` 多副本 / cloud 方案（≥2 worker）时，dict 各副本独立，攻击者只要轮询
不同副本就能绕过限流（5/min 变成 5×N/min）。

**现状**：
- `app/services/rate_limit.py`：纯内存 dict，键 `"{ip}:{scope}"`，每次请求遍历删除过期时间戳
- 调用方：`/api/auth/register, /login, /forgot-password, /reset-password` 各 5/min（forgot 3/min）

**云上改造**：
- 引 `redis>=5.0` + `slowapi` 或自写 `aioredis` 实现同样的滑动窗口
- 接口签名保持 `check_rate_limit(key, limit, window_sec)`，**调用点零修改**
- IP 取值保持 `client_ip(request)`（Nginx 反代时读 `X-Forwarded-For` 链头）
- TTL 设 2× window_sec 自动清空过期键
- 集群版 sentinel 或 cluster：先按单实例 Redis 起步，0.5 天迁移

**验证**：
- 两副本起服务，6 次/分钟请求 → 第 6 次 429（共享 Redis 计数）
- Redis 重启后限流归零（云上已用持久化）

**工作量**：0.5 天（标准库 → Redis 改写 + 集成测试）

---

## 备案通过后接 HTTPS（Day2 待办）

**触发**：腾讯云 134.175.137.41 三容器已上线，但域名备案中，HTTP 直连（裸 IP）。
备案通过后必须切 HTTPS。

**云上改造**：
- 腾讯云控制台申请免费 SSL 证书（TrustAsia DV 单域名）
- nginx 容器挂证书 + 80 强制跳转 443
- 后端 `BaseURL` 从 `http://134.175.137.41` 改 `https://域名`
- 邮件重置链接的 `BASE_URL` 同步改（`app/config.py`）

**验证**：
- `https://域名` 返回 200
- `http://域名` 自动 301 → https
- 重置密码邮件里的链接是 https 开头

**工作量**：0.5 天

---

## 日志集中收集（云上多容器时必备）

**触发**：本地单容器直接看 `uvicorn.err.log`；云上三容器各自一个日志文件，排查时
得 ssh 上去手动 `docker logs`。

**云上改造**：
- 起 `diag-nginx` 反代时加 `access_log /var/log/nginx/access.log main` 写详细日志
- 引入轻量 `promtail + loki` 或干脆 `filebeat + es`（按预算选）
- 告警：5xx > 阈值触发告警（用户注册失败率 / 方案生成失败率）

**验证**：
- Loki/Grafana 或 Kibana 能看到三容器日志
- 告警通道打通（邮件/微信/钉钉）

**工作量**：1 天

---

## 数据库备份与自动恢复

**触发**：本地 SQLite 单库 OK，云上 SQLite 文件丢了=全没。
`backend/data/sqlite.db` 虽 bind mount 持久化，但缺乏定时备份。

**云上改造**：
- 每日 03:00 `sqlite3 .backup` 复制到 `/home/ubuntu/backups/`
- 保留 7 天滚动，超过 7 天删除
- 每周异地备份一次（OSS / 腾讯云 COS）
- 启动时健康检查 DB 文件存在性，缺则从最近备份还原

**验证**：
- 模拟删 DB → 重启 → 数据自动恢复

**工作量**：0.5 天

---

## Secrets 管理（生产环境变量加密）

**触发**：本地 `backend/.env` 直接落盘，密钥明文（DEEPSEEK_API_KEY / 数据库文件路径）。
云上同样的明文 .env 不该直接 commit 到仓库。

**云上改造**：
- 抽 `.env.example`（无密钥）进仓库，`.env` 加 `.gitignore`
- 生产环境用腾讯云 Secrets Manager 或 Vault 注入容器
- compose 文件改 `environment: [SECRET_NAME=...]` → 启动时从 secrets 服务拉

**验证**：
- 仓库里 grep `DEEPSEEK_API_KEY=` 无命中
- 容器启动日志不泄露密钥

---

## 后台管理页面（Day 7-8）

**触发**：本期 MVP 只服务普通用户，无运营/合规视角：
- 谁在跑诊断？什么场景经常被拒？
- 谁用了多少 token？成本归口？
- 异常登录？批量注册？

**云上改造**：
- 后台 `/admin` 页（独立 Basic Auth + IP 白名单）
- 用户列表 / 项目列表 / 诊断成功率 / 平均响应时长
- audit_log 表（谁改了什么 + 何时 + 改前/改后值）

**验证**：
- 运营能从后台看到实时指标
- audit_log 能追责 30 天内的任何改密/改邮箱/删项目操作

**工作量**：1-2 天

---

## 清单更新约定

每完成一项 → 把该条折叠到「已迁移」分区（保留条目 → 不删除，让后人能看到走过哪些路）。