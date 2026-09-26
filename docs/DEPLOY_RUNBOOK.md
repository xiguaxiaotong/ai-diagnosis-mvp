# DEPLOY RUNBOOK —— v2.0 上线日操作手册（备案通过当天照单执行）

> 预案包（W10 Day3）预制完毕。备案通过当天，本手册里的「__填空__」只有：
> 域名、证书、镜像 tag 三个，其余全部照抄命令。
>
> 相关文件：
> - `deploy/nginx.prod.conf.template` —— Nginx 生产模板（80 强跳 443 / SSE 关缓冲）
> - `deploy/docker-compose.prod.yml` —— 生产 compose（镜像 tag 参数化 / 四路径持久化）
> - `deploy/cleanup_smoke.py` —— 冒烟后清生产库 smoke_ 数据
> - 服务器：腾讯云轻量 `134.175.137.41`，部署目录 `/home/ubuntu/ai-diagnosis`，用户 `ubuntu`
> - 本地：`d:\ai-diagnosis-mvp`；python=`C:\Users\31905\miniconda3\python.exe`；
>   node 需 PATH 前缀 `C:\Users\31905\.workbuddy\binaries\node\versions\20.18.0`

---

## 第 0 步 · 前置检查（当天早上，10 分钟）

- [ ] 服务器可登：`ssh ubuntu@134.175.137.41`
- [ ] 服务器代码在最新提交：`cd /home/ubuntu/ai-diagnosis && git log --oneline -1`（或重传 tar，见第 2 步）
- [ ] `.env` 在服务器且 `DEEPSEEK_API_KEY` 有效
- [ ] **torch 离线 wheel 在位**（backend 镜像构建依赖，187MB 不进 git 不随包重传）：
      `ls /home/ubuntu/ai-diagnosis/backend/wheels/torch-*.whl`
      （不在则从本机 `d:\ai-diagnosis-mvp\backend\wheels` 补传，或临时改 Dockerfile 用
      `pip install torch --index-url https://download.pytorch.org/whl/cpu`，慢 5-10 分钟）
- [ ] 磁盘余量：`df -h /home`（镜像 + hf-cache ≥ 5GB 余量）
- [ ] **上线前备份 SQLite**（冒烟清单 9.3）：
      `cd /home/ubuntu/ai-diagnosis/backend && python3 scripts/backup_db.py`
      （产物在 `backend/backups/`，prod compose 已挂载持久化）

---

## 第 1 步 · 本地验证（15 分钟）

```powershell
cd d:\ai-diagnosis-mvp\backend
$env:PYTHONIOENCODING="utf-8"; C:\Users\31905\miniconda3\python.exe -m pytest -m "not llm and not slow" -q
# 预期 143 passed（快速档全绿 = 后端代码可信）

cd d:\ai-diagnosis-mvp\frontend
$env:PATH="C:\Users\31905\.workbuddy\binaries\node\versions\20.18.0;$env:PATH"
npx tsc --noEmit          # 预期零错误
npx next lint             # 预期 No ESLint warnings or errors
```

**构建生产产物（⚠️ 必须先清 .next，见踩坑清单 P4）：**

```powershell
Remove-Item -Recurse -Force .next        # 一定要删！增量缓存可能产出损坏目录
npm run build                            # 预期 ~50s，12 路由全生成
Test-Path .next\BUILD_ID                 # 预期 True —— 上线前必查！！
```

> P4 实锤案例（2026-09-26 预案包验证时复现）：不清 .next 直接 build 可能产出
> **缺 BUILD_ID 的损坏目录**（build 显示成功、Route 表正常打印），用它 COPY 进镜像
> 后容器起不来（"Could not find a production build"）。`Test-Path .next\BUILD_ID`
> 是 30 秒能避免当晚回滚的检查。

---

## 第 2 步 · 上传代码到服务器

> pack.py 会**排除 `.next`**（前端产物不随包走），所以前端构建产物需要方式 B 单独传。

方式 A（后端代码 / 配置 / 种子数据，沿用现有脚本）：

```powershell
cd d:\ai-diagnosis-mvp
C:\Users\31905\miniconda3\python.exe _deploy\pack.py      # 打包 → _deploy\app.tar.gz（~65MB）
C:\Users\31905\miniconda3\python.exe _deploy\deploy.py 134.175.137.41 <ubuntu密码>
# deploy.py 会 SFTP 上传 → 解压到 /home/ubuntu/ai-diagnosis → 后台触发构建
# 注意：deploy.py 最后一步自动 docker compose up 是旧版根目录 compose；
# 上线日建议只走到上传/解压，起服务统一用第 3 步的 prod compose 命令。
```

方式 B（前端产物，必做）：

```bash
# 先清远端旧产物（防 scp -r 嵌套成 frontend/.next/.next）
ssh ubuntu@134.175.137.41 "rm -rf /home/ubuntu/ai-diagnosis/frontend/.next"
```

```powershell
# 1) 后端/配置等走方式 A（同上）
# 2) 前端产物单独传：
cd d:\ai-diagnosis-mvp\frontend
scp -r .next ubuntu@134.175.137.41:/home/ubuntu/ai-diagnosis/frontend/.next
scp package.json package-lock.json next.config.mjs tsconfig.json `
    ubuntu@134.175.137.41:/home/ubuntu/ai-diagnosis/frontend/
```

> （.next 有 3 万+ 小文件，scp 慢的话先 `tar -czf .next.tgz .next` 再传再解压。）

---

## 第 3 步 · 云端构建 + 起服务

```bash
ssh ubuntu@134.175.137.41
cd /home/ubuntu/ai-diagnosis

# 镜像 tag 规范：v主.次.修（当天日期，例 2026-10-20 上线 = v2.0.0）
# build 时 compose 自动把镜像打成该 tag（回滚靠它，见第 8 步）
# ⚠️ 备案没批下来前用第 3A 步（IP 模式）；这是备案通过后的正式姿势
IMAGE_TAG=v2.0.0 DEPLOY_DOMAIN=__你的备案域名__ DEPLOY_SCHEME=https \
  COMPOSE_PROFILES=prod docker compose -f deploy/docker-compose.prod.yml up -d --build

# 构建日志（后台跑 5-10 分钟，torch 装完大头就过了）：
tail -f /tmp/diag-build.log   # 若走 deploy.py 触发；手动跑则直接看终端

# 就绪后三容器状态 + 健康：
COMPOSE_PROFILES=prod docker compose -f deploy/docker-compose.prod.yml ps
curl -s http://localhost/api/health        # 预期 {"status":"ok"}
```

prod compose 相比现行 compose 的变化（细节见文件头注释）：
- 镜像 tag 参数化（`IMAGE_TAG`）——回滚一条命令
- **双模式（W11 Day3）**：`COMPOSE_PROFILES=ip`（备案前 IP 模式）/
  `=prod`（域名模式），见第 3A 步；两套 nginx 服务互斥，模板各用各的
- 四路径持久化：`backend/data`（sqlite+checkpoints）/ `backend/logs`（trace）/
  `backend/backups`（备份）/ `hf-cache`（bge 模型）
- backend 带 healthcheck（urllib，90s start_period 等 alembic 迁移）
- `BASE_URL` / `FRONTEND_ORIGIN` = `${DEPLOY_SCHEME:-http}://${DEPLOY_DOMAIN:-134.175.137.41}`
  （IP 模式 http://IP；域名模式 https://域名，邮件重置链接才正确）

---

## 第 3A 步 · 备案前 IP 模式（域名没批下来，先用 IP 把全链路跑通）

> 备案审核要等 1-2 周，不必干等。IP 模式 = nginx 只听 80（无 ssl、无强跳、
> 无 certs 卷、无 443 映射），`FRONTEND_ORIGIN/BASE_URL = http://134.175.137.41`。
> 备案下来后走第 3B 步 10 分钟切 HTTPS，不用重传任何东西。

首选：`bash deploy/deploy_v2.sh`（DOMAIN 传 IP 自动选 IP 模式，7 步到探活）。
手动等价命令：

```bash
ssh ubuntu@134.175.137.41
cd /home/ubuntu/ai-diagnosis
IMAGE_TAG=v2.0-rc DEPLOY_DOMAIN=134.175.137.41 \
  COMPOSE_PROFILES=ip docker compose -f deploy/docker-compose.prod.yml up -d --build
# 就绪后：nginx-ip 容器（同容器名 diag-nginx，只 80 端口）
COMPOSE_PROFILES=ip docker compose -f deploy/docker-compose.prod.yml ps
curl -s http://localhost/api/health        # 预期 {"status":"ok"}
```

本地验证四条主链路（默认就对准 IP）：
```bash
bash deploy/verify_deployment.sh           # BASE_URL 默认 http://134.175.137.41
```

IP 模式约束（有意为之，别绕）：
- 纯 `http`：登录/诊断/项目全链路可验证；**别在公网传真实用户数据**
  （备案+HTTPS 之前不算合规生产，只做链路验证）
- 邮件重置链接会是 `http://IP/...`——能用但不正式，切 HTTPS 自动修正
- 验证残留（smoke_v 用户）清理：`python3 deploy/cleanup_smoke.py backend/data/sqlite.db`

---

## 第 3B 步 · 备案下来后切 HTTPS（10 分钟内完成）

> 前提：IP 模式已跑通（第 3A 步）。切换 = 换模式变量 + 放证书 + 重 up，
> 代码、数据卷、镜像全部不动。

```bash
# ① DNS 解析 + 证书（第 4/5 步，可与下面并行；certs 放 deploy/certs/）
#    fullchain.pem + privkey.pem（RUNBOOK 第 5 步有完整命令）

# ② 服务器上切换（一条命令，~30s，不重 build）：
ssh ubuntu@134.175.137.41
cd /home/ubuntu/ai-diagnosis
IMAGE_TAG=v2.0-rc DEPLOY_DOMAIN=__你的备案域名__ DEPLOY_SCHEME=https \
  COMPOSE_PROFILES=prod docker compose -f deploy/docker-compose.prod.yml up -d
#    → nginx-ip 容器被 nginx（域名模式）替换：80 强跳 443 + TLS

# ③ 验证：
curl -I http://__域名__              # 预期 301 → https
curl -I https://__域名__             # 预期 200
bash deploy/verify_deployment.sh    # 本地：BASE_URL=https://__域名__ 跑 4 链路
```

切换检查点：
- [ ] `docker compose ps`：diag-nginx 起着（域名模式，443 有监听）
- [ ] 浏览器锁头正常、无告警
- [ ] 邮件重置链接域名已变 `https://域名`（BASE_URL 随 up 更新）
- [ ] `.env` 无需改动（scheme/domain 由 compose 环境变量注入）

---

## 第 4 步 · DNS 解析（10 分钟，备案通过后立即做）

腾讯云控制台 → DNS 解析 DNSPod → 添加记录：

| 主机记录 | 记录类型 | 记录值 |
|---|---|---|
| `@` | A | 134.175.137.41 |
| `www` | A | 134.175.137.41 |

验证（TTL 默认 600s，等几分钟）：

```powershell
nslookup __你的备案域名__
# 解析到 134.175.137.41 即生效；浏览器 http://域名 此时应能打开（nginx 80 会 301 到 https，
# 若证书还没挂则显示证书错误——正常，第 5 步补上）
```

---

## 第 5 步 · HTTPS 证书（15 分钟）

### 主方案：腾讯云免费证书（TrustAsia DV 单域名，推荐）

备案通过后才能签发，当天操作，全程图形界面零命令：

1. 腾讯云控制台 → 搜「SSL 证书」→ **申请免费证书**
2. 域名填 `__你的备案域名__`（www 需要另一张或改用通配符需求另评估；MVP 单域名够用）
3. 验证方式选 **DNS 自动验证**（已在 DNSPod，秒过）→ 等签发（几分钟到半小时）
4. 下载 **Nginx 格式** → 得到 `xxx_bundle.crt` + `xxx.key`
5. 上传并统一命名（nginx 模板写死了这两个名字）：

```bash
scp xxx_bundle.crt ubuntu@134.175.137.41:/home/ubuntu/ai-diagnosis/deploy/certs/fullchain.pem
scp xxx.key         ubuntu@134.175.137.41:/home/ubuntu/ai-diagnosis/deploy/certs/privkey.pem
chmod 600 /home/ubuntu/ai-diagnosis/deploy/certs/privkey.pem   # 服务器上执行
```

6. 生效（nginx 容器重挂证书）：

```bash
cd /home/ubuntu/ai-diagnosis
IMAGE_TAG=v2.0.0 DEPLOY_DOMAIN=__你的备案域名__ DEPLOY_SCHEME=https \
  COMPOSE_PROFILES=prod docker compose -f deploy/docker-compose.prod.yml up -d nginx
```

### 备选方案：certbot（Let's Encrypt，90 天续期，腾讯云证书搞不定时用）

nginx 模板已预留 `/.well-known/acme-challenge/` 路径（webroot 验证）：

```bash
# 服务器上（80 端口被 nginx 占用，走 webroot 模式）
mkdir -p /var/www/certbot
docker run --rm -v /var/www/certbot:/var/www/certbot \
  -v /home/ubuntu/ai-diagnosis/deploy/certs:/etc/letsencrypt \
  certbot/certbot certonly --webroot -w /var/www/certbot \
  -d __你的备案域名__ --email __你的邮箱__ --agree-tos -n
# 产物软链到 fullchain.pem/privkey.pem 后同样重挂 nginx
```

> 续期：cron `0 3 1 * *` 跑一次 certbot renew + `docker compose ... up -d nginx`。

### 验证

```powershell
curl -I http://__你的备案域名__          # 预期 301 → https
curl -I https://__你的备案域名__          # 预期 200
# 浏览器：地址栏锁头正常，无告警
```

---

## 第 6 步 · 生产 API 冒烟（run_smoke 对准生产，约 10 分钟）

本地 pytest 直连生产域名（冒烟套件 = `tests/test_smoke_e2e.py`，12 用例含
真实 LLM 一轮约 4 分钱）。**跑之前有一个填空：admin 白名单预填**——
套件断言「首个注册用户 is_admin」（run_smoke.bat 用全新库保证 id=1=admin，
生产库已有用户，冒烟注册的用户 id 是 max+1，要提前把它加进白名单）：

```bash
# ① 服务器上查当前最大用户 id（得 N，冒烟 admin 将拿到 N+1）
ssh ubuntu@134.175.137.41 \
  "docker exec diag-backend python -c \"import sqlite3; print(sqlite3.connect('/app/data/sqlite.db').execute('select ifnull(max(id),0) from users').fetchone()[0])\""

# ② 服务器 .env 的 ADMIN_USER_IDS 追加 N+1（逗号分隔，原有值保留）
#    例：ADMIN_USER_IDS=3 → 变 ADMIN_USER_IDS=3,58
# ③ 重建 backend 容器使 .env 生效：
cd /home/ubuntu/ai-diagnosis
IMAGE_TAG=v2.0.0 DEPLOY_DOMAIN=__你的备案域名__ \
  docker compose -f deploy/docker-compose.prod.yml up -d backend
```

本地跑（**注意：不设 SMOKE_DB**——本地没有生产库文件，套件自动跳过 DB 级清理、
API 级清理照常执行，残留用户行用第 ⑦ 步脚本清）：

```powershell
cd d:\ai-diagnosis-mvp\backend
$env:SMOKE_E2E="1"
$env:SMOKE_BASE_URL="https://__你的备案域名__"
C:\Users\31905\miniconda3\python.exe -m pytest tests\test_smoke_e2e.py -m smoke -v
# 预期 12 passed（HTTP 层全绿 = DNS/HTTPS/反代/SSE/限流/隔离全链路验证通过）
```

跑完收尾（服务器上）：

```bash
# ④ .env 的 ADMIN_USER_IDS 去掉 N+1，恢复原值
# ⑤ 重建 backend：IMAGE_TAG=v2.0.0 DEPLOY_DOMAIN=__域名__ docker compose -f deploy/docker-compose.prod.yml up -d backend
# ⑥ 手动浏览器抽查三页面：/admin（看板数字）、/projects（历史项目）、诊断页（发一条消息走通）
# ⑦ 清残留（幂等）：
cd /home/ubuntu/ai-diagnosis && python3 deploy/cleanup_smoke.py backend/data/sqlite.db
```

> 注意：冒烟会打满注册限流额度（10 次/小时/本机 IP），**1 小时内本机不能再注册**，
> 对生产无其它影响。真实用户不受牵连（限流按 IP 分桶）。

---

## 第 7 步 · 挂备案号（当天唯一的前端代码改动，~30 分钟）

现状：前端页脚**没有备案号渲染位**（本预案包遵守「零代码改动」约束没有预置）。
备案通过当天做这一处小改：

- `frontend/app/page.tsx`（首页底部）加页脚：
  ICP 备案号链接 `https://beian.miit.gov.cn/`（工信部备案系统）
- 若公安联网备案也下来了（清单 7.2），再加公安备案号 + 链接 `https://beian.mps.gov.cn/`
- 改完走第 1 步前端三关 + build（记得先删 .next）→ 第 2/3 步重传重起

> 清单 7.3：备案未通过前不上线经营功能——当前站为个人非经营性质，注意
> 首页文案不要出现明确经营类表述（「付费」「下单」等），有则一并微调。

---

## 第 8 步 · 回滚（出事时，1 分钟）

前提：每次发布都带递增 tag（第 3 步的 IMAGE_TAG），旧镜像还在服务器上。

```bash
cd /home/ubuntu/ai-diagnosis
docker images | grep diag-          # 找上一个可用 tag，如 v1.9.0

IMAGE_TAG=v1.9.0 DEPLOY_DOMAIN=__域名__ DEPLOY_SCHEME=https \
  COMPOSE_PROFILES=prod docker compose -f deploy/docker-compose.prod.yml up -d   # 只换容器，不重 build，~30s

curl -s http://localhost/api/health   # 预期 {"status":"ok"}
```

回滚注意：
- **数据卷不动**（compose up 换 tag 不会碰 `backend/data` 等 bind mount）
- **数据库迁移单向**：新版本跑过的 alembic 迁移不会自动回退。本项目的迁移
  历史均为加列（nullable），旧代码遇到多出的列不受影响，可安全回滚；
  若未来出现删列/改类型迁移，回滚前先 `python scripts/backup_db.py` 快照
- 镜像清理（防磁盘涨满）：`docker image prune -a`（确认要保留的 tag 之后再跑）

---

## 第 9 步 · 服务器端备份例行化（上线后立刻做，10 分钟）

> 备份的完整闭环 = 自动备份 + 可验证的恢复。本机已用 `backup_full.py` 固化
> （快照 = 主库 + checkpoints + 当日 purge 归档，备份副本 integrity 不过非零退出），
> 服务器上是同一套脚本 + cron。

### 自动备份（cron）

```bash
ssh ubuntu@134.175.137.41
# ① 每天凌晨备份（prod compose 已挂载 backend/backups，容器外宿主机路径即可）
crontab -e
#    加一行（注意 CRON_TZ，见踩坑 P6；备份脚本是纯 python 无容器依赖）：
CRON_TZ=Asia/Shanghai
0 3 * * * cd /home/ubuntu/ai-diagnosis/backend && python3 scripts/backup_full.py >> backups/backup_full.log 2>&1

# ② 磁盘水位：backups 在 compose 里已持久化到宿主机，注意磁盘告警（每份快照 ~1MB 级，7 份无压力）
```

> Windows 本机对应：`backend\scripts\register_backup_task.bat`（schtasks 每天
> 03:00 跑同一脚本，注册后 `/Query` 验证；若已有 W9 的单库备份任务
> AIDiagnosis-DBBackup，两个任务并存无害，也可 `/Delete /F` 换成全量版）。

### 恢复三步（出事时）

```bash
# ① 停服（nginx 可以留着，先停 backend）
cd /home/ubuntu/ai-diagnosis
IMAGE_TAG=v2.0.0 DEPLOY_DOMAIN=__域名__ docker compose -f deploy/docker-compose.prod.yml stop backend

# ② 替换库：dry-run 先校验快照，--apply 才动真库（替换前自动把当前真库快照成 pre_restore_*.db）
python3 scripts/restore_backup.py backups/20260926_030000          # 只校验不写库
python3 scripts/restore_backup.py backups/20260926_030000 --apply   # 真恢复

# ③ 起服 + integrity 已由脚本强制（不 ok 非零退出），起服后验证
IMAGE_TAG=v2.0.0 DEPLOY_DOMAIN=__域名__ docker compose -f deploy/docker-compose.prod.yml up -d backend
curl -s http://localhost/api/health   # 预期 {"status":"ok"}
```

恢复注意：
- `restore_backup.py --apply` 自带「恢复前快照」——恢复操作本身可撤销（再来一次反向恢复即可）；
- 本机恢复同样三步：先停 uvicorn dev server 再 `--apply`（sqlite 被占会写脏页）；
- purge 误删的数据不走本节：用 `purge_test_data.py --restore-file backups/purge_*.json`（W10 Day4 已演练全量恢复逐表一致）。

---

## 第 10 步 · 部署失败回滚（实战包 v2.0-rc · 每个失败点的处置）

> 实战包三脚本（`deploy/bootstrap_server.sh` / `deploy_v2.sh` / `verify_deployment.sh`）
> 每步失败都会自动打印对应回滚提示并退出非零。本节是完整对照表。

| 失败点 | 症状 | 处置（回滚动作） |
|---|---|---|
| 代码传输（deploy_v2 第 1-3 步） | scp 断 / tar 解压失败 | **旧容器未动，无需回滚**——直接重跑 `bash deploy_v2.sh` |
| .env / wheels 前置检查 | grep/ls 失败 | 无回滚动作：填 `DEEPSEEK_API_KEY` 或补传 torch wheel（RUNBOOK 第 0 步）后重跑 |
| compose build/up（第 5 步） | build 报错 / 容器起不来 | `IMAGE_TAG=<上一版tag> DEPLOY_DOMAIN=<域名或IP> COMPOSE_PROFILES=<prod或ip> docker compose -f deploy/docker-compose.prod.yml up -d`（换 tag 不重 build，~30s）；build 报错先看 `docker logs diag-backend --tail 50` |
| 健康检查 90s 未过（第 6 步） | /api/health 一直非 200 | 同上切旧 tag；排查：`ssh 服务器 'docker logs diag-backend --tail 50'`（常见：迁移报错 / DEEPSEEK_API_KEY 空） |
| alembic 迁移失败（第 6 步） | upgrade head 非零 | **停 backend → 恢复库 → 起服**：`compose stop backend` → `python3 scripts/restore_backup.py backups/<最新快照> --apply` → `compose up -d backend`（restore 自带恢复前快照，可反向撤销） |
| 数据校验不过（第 7 步） | users/projects 数 ≠ 12/26 | 传库被换或损坏：重传主库再 up；或按上行恢复备份快照 |
| 最终探活失败（第 7 步） | health ok 过又挂 | 看 `docker logs`；切旧 tag 保服务，事后排查 |
| verify 4 链路失败 | 注册/登录/建项目/SSE 任何一步 | 脚本自动打印回滚命令（IMAGE_TAG 回退）；SSE 无 phase 事件先查服务器 .env 的 DEEPSEEK_API_KEY 是否已填 |

回滚总原则（与第 8 步镜像回滚一致）：
- **数据卷永远不随回滚动**（bind mount 与容器生命周期解耦）；
- 迁移单向：新版本跑过的迁移不回退（本项目历史迁移均为加列，旧代码兼容）；
- 判「回滚成功」的唯一标准：`curl http://localhost/api/health` → `{"status":"ok"}`。

---

## 踩坑清单（上线日异常排查先看这里）

| # | 坑 | 症状 | 处置 |
|---|---|---|---|
| P1 | **SSE 被 nginx 缓冲** | 打字机变 PPT，长任务像死机 | 模板已内置 `proxy_buffering off`；若前面还有 CDN/云 LB，那边也要配 ≥300s 读超时。当时首部署排查了半小时的头号坑 |
| P2 | **NEXT_PUBLIC_API_URL 非空串** | 全站瘫痪（浏览器跨域直连后端 8000，安全组不开放） | prod compose 已写死 `""`（同域相对路径）；排查看浏览器 Network 面板请求 URL 是不是同域 /api |
| P3 | **0.0.0.0 绑定** | 容器间连不通（connection refused） | 后端 Dockerfile / 前端 HOSTNAME=0.0.0.0 已配；若手改过为 127.0.0.1 会只在容器内可达，nginx 容器连不上 |
| P4 | **.next 增量缓存损坏** | 容器起不来："Could not find a production build"（build 却显示成功） | build 前必删 .next；上线前 `Test-Path .next\BUILD_ID` 必查。2026-09-26 预案包验证时实际复现过 |
| P5 | **trace/日志路径不持久化** | 容器重建后 W8 诊断轨迹全丢 | prod compose 已挂 `backend/logs:/app/logs`（TRACE_PATH 默认 /app/logs/trace.jsonl） |
| P6 | **时区分桶错位** | admin 看板「近 14 天」日期少一天/跨天错位 | 后端容器 `TZ=Asia/Shanghai` 已设；宿主机 crontab（备份任务）注意 `CRON_TZ=Asia/Shanghai` 或服务器时区统一；sqlite 存的是 naive UTC，看板聚合用 ZoneInfo("Asia/Shanghai") 转，别用 UTC 分桶 |
| P7 | **wheels 不在服务器** | backend 镜像 build 第一步 COPY wheels 失败 | 见第 0 步前置检查；pack.py 打包刻意排除（187MB 不重复传） |
| P8 | **hf-cache 不挂载** | 容器重建后 bge 模型重新下载（慢 + 可能超时） | prod compose 已挂 `../hf-cache:/data/hf-cache` |
| P9 | **邮件重置链接域名错误** | 重置密码邮件里的链接是 localhost / 裸 IP | prod compose `BASE_URL=https://__域名__` 已自动拼好；改域名要重 up backend |
| P10 | **上传大文件 413** | 用户传带图 PDF 失败 | nginx `client_max_body_size 20m` 已配；若调后端限制记得两边同步 |

---

## 快速对照：当天时间线（备案通过 → 上线完成 ≈ 2 小时）

```
T+0:00  DNS 解析添加 A 记录（第 4 步，先让解析生效跑着）
T+0:05  腾讯云申请免费证书（第 5 步①-③，等签发期间并行做后面）
T+0:10  本地验证 + 前端 build（第 1 步，记得先删 .next）
T+0:30  上传代码 + 云端 build（第 2/3 步，IMAGE_TAG=v2.0.0）
T+0:50  证书下载挂载 + nginx 起 443（第 5 步④-⑥）
T+1:00  生产 API 冒烟 12 用例（第 6 步，含 admin id 预填）
T+1:20  浏览器三页面抽查 + 清冒烟数据
T+1:30  挂备案号（第 7 步，唯一代码改动；当天来不及可次日）
T+2:00  完成。git tag v2.0-release + 服务器镜像 tag 快照记录
```
