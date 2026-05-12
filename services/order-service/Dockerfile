FROM node:20-alpine AS builder
WORKDIR /app

COPY package*.json ./
COPY shared/common/package*.json shared/common/
COPY services/order-service/package*.json services/order-service/

RUN npm install --workspace=@agentic-commerce/common --workspace=@agentic-commerce/order-service --include-workspace-root

COPY shared/common/ shared/common/
COPY services/order-service/ services/order-service/

RUN npm run build --workspace=@agentic-commerce/common
RUN npm run build --workspace=@agentic-commerce/order-service

FROM node:20-alpine AS runtime
WORKDIR /app

USER node
COPY --chown=node:node --from=builder /app/node_modules ./node_modules
COPY --chown=node:node --from=builder /app/package.json ./package.json
COPY --chown=node:node --from=builder /app/shared/common/dist ./shared/common/dist
COPY --chown=node:node --from=builder /app/shared/common/package.json ./shared/common/package.json
COPY --chown=node:node --from=builder /app/services/order-service/dist ./services/order-service/dist
COPY --chown=node:node --from=builder /app/services/order-service/package.json ./services/order-service/package.json

ENV NODE_ENV=production PORT=3003
WORKDIR /app/services/order-service
EXPOSE 3003

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3003/healthz',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "dist/server.js"]
