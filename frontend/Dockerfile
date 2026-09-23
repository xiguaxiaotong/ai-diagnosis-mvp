# 前端镜像：跳过容器内 build，直接 COPY 本地 npm run build 的产物 .next
#
# 为什么不在镜像里 build：腾讯云 2C4G 跑 npm run build 极慢（十几分钟），而
# 开发者本机 CPU 强几十倍，几秒出 .next。把 .next 打包进镜像，运行时 npm start
# 启动 Next 生产服务，CPU 几乎不吃（已编译产物只做静态文件分发 + API 反代）。
#
# 前置（开发者本机执行一次）：
#   cd frontend
#   echo NEXT_PUBLIC_API_URL= > .env.production   # 空串 = 同域 /api 反代
#   npm run build                                  # 生成 .next/
#
# 后续每次修改代码：
#   本机重 build → 重新打包 → 服务器 up -d --build（数十秒即可完成）

FROM node:20-alpine
WORKDIR /app

# 装运行时依赖（next/react 等 dev 已被剔除，镜像层只装 production deps）
COPY package.json package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com \
    && npm ci --omit=dev

# 本机构建好的产物直接 COPY（这是整个 Dockerfile 的核心：跳过容器内 build）
COPY .next ./.next
COPY next.config.* ./
COPY tsconfig.json ./

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

EXPOSE 3000
CMD ["npm", "run", "start"]