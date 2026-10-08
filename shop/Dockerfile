# 顾客端镜像：Node 多阶段构建 → standalone 运行。
#
# 构建上下文是 /shop（Railway Root Directory），拿不到仓库根的 docs/ 与 frontend/。
# 所以这里**不跑 codegen 与 token 同步**——src/api/generated.ts、src/styles/tokens.css、
# public/borough-logo.svg 都是提交进仓库的副本，由 npm run codegen:check / tokens:check
# 在本地与 CI 保证没有过期。

FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:24-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# NEXT_PUBLIC_* 在构建期内联进浏览器产物，必须由部署平台提供；
# 缺失时 src/api/client.ts 会抛出配置错误，不回退同源 /api。
ARG NEXT_PUBLIC_API_BASE_URL
ENV NEXT_PUBLIC_API_BASE_URL=$NEXT_PUBLIC_API_BASE_URL
ARG NEXT_PUBLIC_DEFAULT_SHOP_SLUG
ENV NEXT_PUBLIC_DEFAULT_SHOP_SLUG=$NEXT_PUBLIC_DEFAULT_SHOP_SLUG
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:24-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
# standalone 输出自带最小 node_modules 与 server.js；静态资源与 public 需要单独带上。
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
USER node
# Railway 通过 $PORT 指定监听端口；server.js 读取 PORT 与 HOSTNAME。
ENV HOSTNAME=0.0.0.0
EXPOSE 3000
CMD ["node", "server.js"]
