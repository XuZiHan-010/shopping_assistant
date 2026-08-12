# 前端静态镜像：Node 构建 → Caddy 托管。
#
# 构建上下文是 /frontend（AGENTS.md §十四 的 Railway Root Directory），拿不到
# 仓库根的 docs/。所以这里**不跑 npm run codegen**——src/api/generated.ts 是提交
# 进仓库的生成产物，由 npm run codegen:check 在本地和 CI 保证它没有过期。

FROM node:24-alpine AS build
WORKDIR /app

# 先只复制清单，让依赖层能命中缓存。
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# VITE_API_BASE_URL 在构建期注入静态产物，必须由部署平台提供；
# 缺失时 src/api/client.ts 会抛出可展示的中文配置错误。
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
# 刻意声明这个 ARG：不是为了让生产开启 Mock，而是让 src/build/mock-flag.ts
# 的防线在镜像构建里也能看到它。不声明的话，误配 VITE_USE_MOCK=true 会被
# 静默忽略，防线形同虚设。
ARG VITE_USE_MOCK
ENV VITE_USE_MOCK=$VITE_USE_MOCK
RUN npm run build

FROM caddy:2-alpine AS runtime
COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv

# Railway 通过 $PORT 指定监听端口，Caddyfile 里已用 {$PORT:80} 兜底。
EXPOSE 80
