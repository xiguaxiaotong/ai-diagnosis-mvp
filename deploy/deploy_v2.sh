#!/usr/bin/env bash
# =====================================================================
# 一键部署 v2.0-rc（W11 Day2 · 云端部署实战包 · 步骤 2/3）
#
# 按 docs/DEPLOY_RUNBOOK.md 顺序执行：打包传码 → compose up → 迁移 →
# 数据校验（白名单 12 用户 / 26 项目）→ 探活。每步失败立即退出并打印
# 回滚提示。
#
# 用法（本地，Git Bash / WSL）：
#   bash deploy_v2.sh                    # 真部署
#   DRY_RUN=1 bash deploy_v2.sh          # 只打印将执行的命令
#
# 可配环境变量（默认值见下）：
#   SERVER=ubuntu@134.175.137.41
#   DOMAIN=<域名或 IP>         # 必须提供。IP=备案前 IP 模式（http，80 端口，
#                              # 无 ssl/certs）；域名=域名模式（https+TLS）
#   IMAGE_TAG=v2.0-rc
#
# 模式自动选择（W11 Day3）：DOMAIN 是 IPv4 → COMPOSE_PROFILES=ip
# （nginx.ip.conf.template / http://IP / 不挂 443 与 certs）；是域名 →
# COMPOSE_PROFILES=prod（80 强跳 443 + TLS）。备案下来后把 DOMAIN 换成
# 域名重跑本脚本即自动升级 HTTPS。
#
# 回滚点（每步失败时的处置详见 RUNBOOK「部署失败回滚」一节）：
#   - 代码传输失败      → 旧容器未动，直接重跑本脚本
#   - build/up 失败     → IMAGE_TAG=<上一版> 重跑 up -d（不重 build）
#   - 迁移/校验/探活失败 → stop backend → restore_backup --apply → 起服
# =====================================================================
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
SERVER="${SERVER:-ubuntu@134.175.137.41}"
DOMAIN="${DOMAIN:?必须提供 DOMAIN（域名或 IP）：bash deploy_v2.sh 前 export DOMAIN=134.175.137.41 或备案域名}"
IMAGE_TAG="${IMAGE_TAG:-v2.0-rc}"
REMOTE_DIR="/home/ubuntu/ai-diagnosis"

# W11 Day3：IP 还是域名，自动定模式（nginx 模板 / scheme / compose profile）
if [[ "$DOMAIN" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
  MODE=ip; SCHEME=http
else
  MODE=prod; SCHEME=https
fi
COMPOSE="COMPOSE_PROFILES=$MODE docker compose -f deploy/docker-compose.prod.yml"

run() {           # 远程/本地命令统一走这里（dry-run 只打印）
  echo "+ $*"
  [ "$DRY_RUN" = "1" ] || "$@"
}

fail() {          # 步骤失败：打印回滚提示后退出
  echo ""
  echo "❌ 部署失败于：$1"
  echo "   回滚提示：旧镜像未删除，执行"
  echo "     ssh $SERVER 'cd $REMOTE_DIR && IMAGE_TAG=<上一版tag> DOMAIN=$DOMAIN $COMPOSE up -d'"
  echo "   详见 docs/DEPLOY_RUNBOOK.md「部署失败回滚」一节"
  exit 1
}

echo "== 模式：DOMAIN=$DOMAIN → ${SCHEME}://${DOMAIN}（profile=$MODE）=="

echo "== [1/7] 本地打包（pack.py，产物 _deploy/app.tar.gz，含 backend/data 清理后主库）=="
run python _deploy/pack.py

echo "== [2/7] 上传代码包并解压 =="
run scp _deploy/app.tar.gz "$SERVER:/tmp/app.tar.gz"
run ssh "$SERVER" "cd $REMOTE_DIR && tar -xzf /tmp/app.tar.gz && rm /tmp/app.tar.gz"

echo "== [3/7] 前端构建产物单独传（.next 先 tar 防嵌套，先清远端旧产物防残留）=="
run bash -c "cd frontend && tar -czf /tmp/next.tgz .next"
run ssh "$SERVER" "rm -rf $REMOTE_DIR/frontend/.next"
run scp /tmp/next.tgz "$SERVER:/tmp/next.tgz"
run ssh "$SERVER" "cd $REMOTE_DIR/frontend && tar -xzf /tmp/next.tgz && rm /tmp/next.tgz"

echo "== [4/7] 前置检查：.env 已填 / torch wheel 在位 =="
run ssh "$SERVER" "grep -q '^DEEPSEEK_API_KEY=..' $REMOTE_DIR/.env" \
  || fail ".env 未填 DEEPSEEK_API_KEY"
run ssh "$SERVER" "ls $REMOTE_DIR/backend/wheels/torch-*.whl" \
  || fail "torch 离线 wheel 不在服务器（见 RUNBOOK 第 0 步）"

echo "== [5/7] compose 构建 + 起三容器（首次 build 5-10 分钟，torch 装完大头就过）=="
run ssh "$SERVER" "cd $REMOTE_DIR && IMAGE_TAG=$IMAGE_TAG DEPLOY_DOMAIN=$DOMAIN DEPLOY_SCHEME=$SCHEME $COMPOSE up -d --build" \
  || fail "compose build/up（镜像构建失败）"

echo "== [6/7] 等健康（healthcheck start_period 90s 内含 alembic 迁移）+ 迁移确认 =="
for i in $(seq 1 30); do
  if [ "$DRY_RUN" = "1" ]; then echo "+ ssh $SERVER curl -s http://localhost/api/health（第 $i 次重试，dry-run 跳过）"; break; fi
  if run ssh "$SERVER" "curl -sf http://localhost/api/health"; then echo "  health ok"; break; fi
  [ "$i" = "30" ] && fail "健康检查 90 秒未通过（看日志：ssh $SERVER 'docker logs diag-backend --tail 50'）"
  sleep 3
done
run ssh "$SERVER" "cd $REMOTE_DIR && IMAGE_TAG=$IMAGE_TAG DEPLOY_DOMAIN=$DOMAIN DEPLOY_SCHEME=$SCHEME $COMPOSE exec -T backend alembic upgrade head" \
  || fail "alembic 迁移"

echo "== [7/7] 数据校验（白名单 12 用户 / 26 项目）+ 探活 =="
run ssh "$SERVER" "docker exec diag-backend python -c \"
import sqlite3
con = sqlite3.connect('/app/data/sqlite.db')
u = con.execute('select count(*) from users').fetchone()[0]
p = con.execute('select count(*) from projects').fetchone()[0]
l = con.execute('select count(*) from leads').fetchone()[0]
print(f'users={u} projects={p} leads={l}')
assert (u, p, l) == (12, 26, 12), f'数据校验不过：期望 12/26/12'
\"" \
  || fail "数据校验（users/projects 数量与预期不符——库被换过或传输损坏）"
run ssh "$SERVER" "curl -sf http://localhost/api/health" \
  || fail "最终探活"

echo ""
echo "✅ v2.0-rc 部署完成（IMAGE_TAG=$IMAGE_TAG）。下一步：verify_deployment.sh 跑 4 条主链路"
