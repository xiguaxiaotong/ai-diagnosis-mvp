#!/usr/bin/env bash
# =====================================================================
# 部署后验证（W11 Day2 · 云端部署实战包 · 步骤 3/3）
#
# 对准部署好的服务跑通 4 条主链路：注册 → 登录 → 建项目 → 诊断 SSE
# （真实 LLM 一轮，约 4 分钱）+ 项目列表。任何一步失败打印明确的
# 回滚提示（IMAGE_TAG 回退上一版）。数据带 smoke_v 前缀，项目验完即删；
# 注册用户行（无删除 API）用 deploy/cleanup_smoke.py 收尾。
#
# 用法（本地，Git Bash / WSL）：
#   bash verify_deployment.sh                          # 对默认地址
#   BASE_URL=https://域名 bash verify_deployment.sh    # 证书挂好后
#   DRY_RUN=1 bash verify_deployment.sh                # 只打印将执行的命令
#
# 注意：注册限流 10 次/小时/IP——1 小时内重复跑本脚本会 429。
# =====================================================================
set -euo pipefail

DRY_RUN="${DRY_RUN:-0}"
BASE_URL="${BASE_URL:-http://134.175.137.41}"
PREV_TAG="${PREV_TAG:-<上一版tag>}"
SERVER="${SERVER:-ubuntu@134.175.137.41}"

SUFFIX="v$(date +%H%M%S)"                 # smoke_v 前缀 + 时分秒，重跑不撞
USER="smoke_vuser_$SUFFIX"
PASS="smoke_pass_1"
IDEA="我想在小区里做一个宠物临时寄养的小程序，帮邻居出差时托管猫狗"

# dry-run 的完整命令清单模式：不执行、不断言，只打印
dry() { echo "+ $*"; }

rollback() {      # 失败统一出口：明确回滚指令
  echo ""
  echo "❌ 部署验证失败于步骤：$1"
  echo "   回滚命令（把服务切回上一版镜像，容器换 tag 不重 build，约 30 秒）："
  echo "     ssh $SERVER 'cd /home/ubuntu/ai-diagnosis && \\"
  echo "       IMAGE_TAG=$PREV_TAG DEPLOY_DOMAIN=<你的域名> \\"
  echo "       docker compose -f deploy/docker-compose.prod.yml up -d'"
  echo "   回滚后 curl $BASE_URL/api/health 应为 {\"status\":\"ok\"}"
  echo "   残留 smoke_v 数据清理：ssh $SERVER 'python3 deploy/cleanup_smoke.py backend/data/sqlite.db'"
  exit 1
}

# jq 可缺省：没有就用 python 解析（|| true：解析失败交给后面的
# [ -n ] 检查走 rollback，别让 set -e 在赋值处静默退出——W11 Day3
# 实战踩坑：建项目 400 时 PID=$(...) 解析失败直接哑退，无任何报错）
_json() { python -c "import json,sys; print(json.load(sys.stdin)$1)" 2>/dev/null || true; }

echo "== 部署验证开始 → $BASE_URL（用户 $USER，DRY_RUN=$DRY_RUN）=="

echo "== [1/5] 健康探活 =="
if [ "$DRY_RUN" = "1" ]; then
  dry "curl -sf --max-time 10 $BASE_URL/api/health   # 期望 {\"status\":\"ok\"}"
else
  curl -sf --max-time 10 "$BASE_URL/api/health" | grep -q '"ok"' \
    || rollback "0 健康探活（服务没起来或 nginx 没通）"
fi

echo "== [2/5] 注册 → 201 + token =="
if [ "$DRY_RUN" = "1" ]; then
  dry "curl -s -X POST $BASE_URL/api/auth/register -H 'Content-Type: application/json' \\"
  dry "     -d '{\"username\":\"$USER\",\"password\":\"$PASS\"}'   # 期望 201 + token"
else
  REGISTER_JSON=$(curl -s --max-time 10 -X POST "$BASE_URL/api/auth/register" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}") || rollback "1 注册（网络/服务异常）"
  echo "  $REGISTER_JSON" | head -c 200; echo ""
  TOKEN=$(echo "$REGISTER_JSON" | _json "['token']")
  [ -n "${TOKEN:-}" ] || rollback "1 注册（响应无 token：$REGISTER_JSON）"
fi

echo "== [3/5] 登录 → 200 + token =="
if [ "$DRY_RUN" = "1" ]; then
  dry "curl -s -X POST $BASE_URL/api/auth/login -H 'Content-Type: application/json' \\"
  dry "     -d '{\"username\":\"$USER\",\"password\":\"$PASS\"}'   # 期望 200 + token"
else
  LOGIN_JSON=$(curl -s --max-time 10 -X POST "$BASE_URL/api/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}") || rollback "2 登录"
  LTOKEN=$(echo "$LOGIN_JSON" | _json "['token']")
  [ -n "${LTOKEN:-}" ] || rollback "2 登录（$LOGIN_JSON）"
fi

echo "== [4/5] 建项目 → 201 =="
if [ "$DRY_RUN" = "1" ]; then
  dry "curl -s -X POST $BASE_URL/api/projects -H 'Authorization: Bearer <token>' \\"
  dry "     -d @<bodyfile>（title/raw_idea 含中文）   # 期望 201"
else
  # 中文 payload 落盘用 -d @file：Windows Git Bash 的 curl 会把命令行里的
  # 中文按 ANSI(GBK) 转码发出，服务端 JSON 解析直接 400——W11 Day3 实战
  # 踩坑；@文件传原始 UTF-8 字节，跨平台都对
  PROJ_BODY=$(mktemp)
  printf '%s' "{\"title\":\"smoke_v 部署验证 $SUFFIX\",\"raw_idea\":\"$IDEA\"}" > "$PROJ_BODY"
  PROJ_JSON=$(curl -s --max-time 10 -X POST "$BASE_URL/api/projects" \
    -H "Content-Type: application/json" -H "Authorization: Bearer $LTOKEN" \
    -d @"$PROJ_BODY") || { rm -f "$PROJ_BODY"; rollback "3 建项目"; }
  rm -f "$PROJ_BODY"
  PID=$(echo "$PROJ_JSON" | _json "['id']")
  [ -n "${PID:-}" ] || rollback "3 建项目（$PROJ_JSON）"
fi

echo "== [5/5] 诊断 SSE 一轮（真实 LLM，读超时 300s）+ 项目列表 =="
if [ "$DRY_RUN" = "1" ]; then
  dry "curl -sN --max-time 300 -X POST $BASE_URL/api/chat -H 'Authorization: Bearer <token>' \\"
  dry "     -d '{\"project_id\":<pid>,\"message\":\"$IDEA\"}'   # 期望 SSE data: 事件流含 phase"
  dry "curl -sf $BASE_URL/api/projects -H 'Authorization: Bearer <token>'   # 期望列表含新项目"
  dry "curl -s -X DELETE $BASE_URL/api/projects/<pid> -H 'Authorization: Bearer <token>'   # 收尾删项目"
  echo ""
  echo "✅ DRY-RUN 完成：以上为将执行的完整命令清单，未发任何请求。"
  exit 0
fi
SSE_FILE=$(mktemp)
SSE_BODY=$(mktemp)
printf '%s' "{\"project_id\":$PID,\"message\":\"$IDEA\"}" > "$SSE_BODY"
curl -sN --max-time 300 -X POST "$BASE_URL/api/chat" \
  -H "Content-Type: application/json" -H "Authorization: Bearer $LTOKEN" \
  -d @"$SSE_BODY" -o "$SSE_FILE" \
  || { rm -f "$SSE_FILE" "$SSE_BODY"; rollback "4 诊断 SSE（超时/断流）"; }
rm -f "$SSE_BODY"
EVENTS=$(grep -c '^data: ' "$SSE_FILE" || true)
echo "  SSE 事件数：$EVENTS"
grep -q '"phase"' "$SSE_FILE" || { rm -f "$SSE_FILE"; rollback "4 诊断 SSE（无 phase 事件——LLM 未接通？查 DEEPSEEK_API_KEY）"; }
rm -f "$SSE_FILE"
curl -sf --max-time 10 "$BASE_URL/api/projects" -H "Authorization: Bearer $LTOKEN" \
  | grep -q "\"id\":$PID" || rollback "5 项目列表（刚建的项目不在列表里）"

echo "== 收尾：删验证项目（smoke_v 用户行留给 cleanup_smoke.py）=="
curl -s --max-time 10 -X DELETE "$BASE_URL/api/projects/$PID" \
  -H "Authorization: Bearer $LTOKEN" || true

echo ""
echo "✅ 4 条主链路全通（注册/登录/建项目/诊断SSE + 列表）。部署验证通过。"
