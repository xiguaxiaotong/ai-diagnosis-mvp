#!/usr/bin/env bash
# =====================================================================
# 服务器初始化（W11 Day2 · 云端部署实战包 · 步骤 1/3）
#
# 在腾讯云服务器上跑一次：装 docker/compose、建部署目录、生成 .env 模板
# （密钥值留空，由使用者填）。幂等：重复跑不覆盖已有 .env。
#
# 用法（服务器上）：
#   bash bootstrap_server.sh              # 真执行（需要 sudo）
#   DRY_RUN=1 bash bootstrap_server.sh    # 只打印将执行的命令
#
# 回滚点：本脚本只装依赖建目录，不动业务代码与数据；
#   卸载 = 删 /home/ubuntu/ai-diagnosis + apt remove docker.io。
# =====================================================================
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
BASE_DIR="${BASE_DIR:-/home/ubuntu/ai-diagnosis}"

run() {           # 打印并执行（dry-run 只打印）
  echo "+ $*"
  [ "$DRY_RUN" = "1" ] || "$@"
}

echo "== [1/4] 安装 Docker + Compose 插件 =="
if [ "$DRY_RUN" != "1" ] && command -v docker >/dev/null 2>&1; then
  echo "  docker 已安装：$(docker --version)，跳过安装"
else
  run apt-get update -qq
  run apt-get install -y -qq docker.io docker-compose-v2
fi
run systemctl enable --now docker
if [ "$DRY_RUN" != "1" ]; then docker compose version; fi

echo "== [2/4] ubuntu 用户加入 docker 组（免 sudo 跑 compose）=="
run usermod -aG docker ubuntu

echo "== [3/4] 建部署目录树 =="
run mkdir -p "$BASE_DIR"/backend/data "$BASE_DIR"/backend/logs \
             "$BASE_DIR"/backend/backups "$BASE_DIR"/backend/wheels \
             "$BASE_DIR"/deploy/certs "$BASE_DIR"/hf-cache
run chown -R ubuntu:ubuntu "$BASE_DIR"

echo "== [4/4] 生成 .env 模板（值留空，使用者填；已存在则不覆盖）=="
if [ -f "$BASE_DIR/.env" ]; then
  echo "  .env 已存在，跳过（不覆盖）"
else
  if [ "$DRY_RUN" = "1" ]; then
    echo "  [DRY] 将创建 $BASE_DIR/.env，内容如下："
    sed 's/^/  | /' <<'ENVEOF'
# ==== AI 诊断平台 生产 .env（填空后生效）====
# 必填：DeepSeek API Key
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
# admin 白名单（逗号分隔 user.id；新库首个注册用户 id=1）
ADMIN_USER_IDS=1
# 限流总开关（生产必须 true）
RATE_LIMIT_ENABLED=true
# 前端同源（CORS 兜底；compose 会覆盖为 https://域名）
FRONTEND_ORIGIN=
# 其余（CHAT_MODEL/EMBEDDING_MODEL_NAME 等）走默认值，不用填
ENVEOF
  else
    cat > "$BASE_DIR/.env" <<'ENVEOF'
# ==== AI 诊断平台 生产 .env（填空后生效）====
# 必填：DeepSeek API Key
DEEPSEEK_API_KEY=
DEEPSEEK_BASE_URL=https://api.deepseek.com
# admin 白名单（逗号分隔 user.id；新库首个注册用户 id=1）
ADMIN_USER_IDS=1
# 限流总开关（生产必须 true）
RATE_LIMIT_ENABLED=true
# 前端同源（CORS 兜底；compose 会覆盖为 https://域名）
FRONTEND_ORIGIN=
# 其余（CHAT_MODEL/EMBEDDING_MODEL_NAME 等）走默认值，不用填
ENVEOF
    chmod 600 "$BASE_DIR/.env"
    echo "  已创建 $BASE_DIR/.env（600 权限）——请填 DEEPSEEK_API_KEY"
  fi
fi

echo "✅ 服务器初始化完成（DRY_RUN=$DRY_RUN）。下一步：deploy_v2.sh"
