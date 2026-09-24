# W7 上云安全清单（云部署前必查）

> 本清单是**真正上云（域名 + HTTPS + 公网 IP）前**必须解决的项。  
> 本机 localhost 开发不受此清单约束。  
> Day6（2026-09-24）起开始累积，每完成一项在「已处理」打勾。

## 已处理（Day5-Day6）

- [x] **admin 鉴权白名单**：`ADMIN_USER_IDS` env（逗号分隔 user.id），默认空集 = 无人 admin  
  实现：`backend/app/config.py` + `backend/app/api/auth.py:require_admin`
- [x] **admin 接口不依赖前端 admin 标识**：前端 `getUser().is_admin` 只用于显示入口，每次接口调用仍走后端 require_admin 校验  
  防御：前端绕过不可单独授权
- [x] **admin 完整手机号**：上云时 admin 接口必须受 IP 白名单 + VPN 双重保护（见下方「待办」）

## 待办（云部署前必须完成）

### A. admin 完整手机号接口强保护

**问题**：`/api/admin/leads*` 系列接口返回完整手机号（admin 要打电话/加微信），泄漏 = 客户隐私事故。  
**当前防护**：仅 ADMIN_USER_IDS 白名单。  
**上云前必加**：

- [ ] **IP 白名单**（Nginx / Cloudflare / SLB 层）：仅运营办公室固定 IP 可访问 `/api/admin/*`  
  配置示例（Nginx）：
  ```
  location /api/admin/ {
      allow 1.2.3.4;       # 运营办公室公网 IP
      allow 5.6.7.8;       # 备用 IP（如出差酒店）
      deny all;
      proxy_pass http://backend;
  }
  ```
- [ ] **VPN 二次保护**：admin 客户端强制走公司 VPN；双重保险（IP 白名单被绕过的场景）
- [ ] **操作审计日志**：所有 PATCH /leads/{id}、POST /leads/{id}/notes 写 admin_audit 表（admin_id / action / target / ip / ts）  
  Day6 已在 lead_notes 表带 admin_id，可直接复用；后期可独立 audit 表
- [ ] **MFA（多因素认证）**：admin 登录需短信/邮箱验证码（MVP 暂不强求；v1 必须）
- [ ] **会话超时**：admin token 7 天过期（用户侧 30 天；admin 更短）

### B. 日志不打印手机号

**问题**：admin 看完整手机号，代码里若 print / log 出来（异常 traceback / 调试 logger.info）会进文件 / ELK / 钉钉机器人 → 一旦泄漏即发生。  
**当前防护**：Day6 已在 `app.infra.callbacks:PhoneMaskingFilter` 给所有 app logger 装过滤器，源头脱敏 11 位中国手机号 → `138****0001`。  
**测试**：手动 `logger.info("测试手机号 13812345678")` 应输出 `测试手机号 138****0001`。  
**上云前必做**：

- [ ] **ELK / 文件日志级别 ≥ INFO**：DEBUG 会打印 raw 数据，建议云上生产 INFO / WARNING
- [ ] **手机号正则定期更新**：运营商新号段（如 192/196 5G 号段）若入正则白名单需更新（已支持 `[3-9]` 第二位，覆盖现有所有 11 位号段）
- [ ] **exc_info 内的手机号**：当前仅脱敏 msg / args，traceback 内手机号不脱敏；靠「不要把手机号打到 traceback」+「日志权限最小化」控制
- [ ] **运维巡检**：每月抽样 5 条 uvicorn 日志确认无完整手机号

### C. CORS / Origin / CSRF

- [ ] **FRONTEND_ORIGIN 严格**：禁止 `*`，只允许真实域名（`https://yourdomain.com`）
- [ ] **Cookie SameSite=Strict + Secure**（v1 启用 cookie 鉴权时）
- [ ] **CSRF token**（如未来改 cookie 鉴权必加；当前 Bearer token 无 CSRF 风险）

### D. 数据层

- [ ] **数据库备份**：每日全量 + 1 小时 binlog；备份异地存储（腾讯云 COS）
- [ ] **数据库访问白名单**：DB 仅 8000 端口来源可连；admin 客户端无直连 DB 权限
- [ ] **敏感字段加密**：手机号 / 邮箱 列加密存储（KMS）—— 当前明文，按合规要求 P0
- [ ] **删除项目数据保留期**：用户删项目后，关联 leads / conversations N 天后真删（GDPR）

### E. 文件 / 上传

- [ ] **上传文件类型白名单**：pdf/docx/md/jpg/png；禁止 exe/zip
- [ ] **上传大小限制**：20MB（已有）；云端 Nginx 二次限制防穿
- [ ] **文件存储隔离**：上传文件不进 git；云端用对象存储 + 签名 URL

### F. LLM / API Key

- [ ] **API key 不入日志**：当前 logger 不打印 key，但需云端 grep 验证
- [ ] **DeepSeek key 限额 / 告警**：超过日预算 80% 触发告警
- [ ] **prompt 注入记录**：Day4 已有 `_INJECTION_KEYWORDS` 扫描；上云后写专门审计表

### G. 监控 / 告警

- [ ] **5xx 告警**：连续 1 分钟 > 1% → 钉钉
- [ ] **admin 接口异常访问**：非白名单 IP 访问 `/api/admin/*` → 钉钉（IP 白名单拦的，但万一配置错）
- [ ] **数据库慢查询**：> 1s 告警

### H. 部署 / 运维

- [ ] **HTTPS 强制**：腾讯云免费证书 / Let's Encrypt；HTTP → HTTPS 301
- [ ] **HSTS**：1 年 max-age
- [ ] **关掉 server banner**：Nginx `server_tokens off`、uvicorn 禁 banner
- [ ] **依赖漏洞扫描**：`pip-audit` + `npm audit`，每次 deploy 前跑

## 当前进度

| 类别 | 已做 | 待做 |
|---|---|---|
| admin 鉴权 | 白名单 + 后端强校验 | IP 白名单 + VPN + MFA |
| 日志脱敏 | 源头 filter | ELK 级别 / 异步入库 / 巡检 |
| CORS | dev 允许多 origin | 生产严格 ORIGIN |
| 数据加密 | 明文 | KMS 加密手机号邮箱 |
| 监控 | 无 | 5xx + admin 异常 + 慢查询 |

## 上云流程 checklist（部署日）

1. 域名 ICP 备案已通过（Day2 用户提交中）
2. HTTPS 证书已签发 + 自动续期
3. ADMIN_USER_IDS 改成真实运营账号 user.id（不要保留 1 / 测试值）
4. IP 白名单 + VPN 已配（运维确认）
5. 日志采集（ELK / 文件）已挂载 + 抽样确认无完整手机号
6. 数据库备份已开
7. 监控 / 告警已配 + 钉钉测试
8. 灰度：先 1% 流量 → 5% → 全量
9. CDN / WAF 已挂（防 CC / SQL 注入）

---

**维护人**：自己  
**最后更新**：2026-09-24（W7 Day6 / 起累积）