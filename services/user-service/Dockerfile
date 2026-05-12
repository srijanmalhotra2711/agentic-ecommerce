# Build context: REPO ROOT (so we can include the shared package).
# This Dockerfile expects to be built with `context: .` in docker-compose.

# ---- Builder ----
FROM node:20-alpine AS builder
WORKDIR /app

COPY package*.json ./
COPY shared/common/package*.json shared/common/
COPY services/user-service/package*.json services/user-service/

RUN npm install --workspace=@agentic-commerce/common --workspace=@agentic-commerce/user-service --include-workspace-root

COPY shared/common/ shared/common/
COPY services/user-service/ services/user-service/

# Build the shared package, then the service
RUN npm run build --workspace=@agentic-commerce/common
RUN npm run build --workspace=@agentic-commerce/user-service

# ---- Runtime ----
FROM node:20-alpine AS runtime
WORKDIR /app

USER node
COPY --chown=node:node --from=builder /app/node_modules ./node_modules
COPY --chown=node:node --from=builder /app/package.json ./package.json
COPY --chown=node:node --from=builder /app/shared/common/dist ./shared/common/dist
COPY --chown=node:node --from=builder /app/shared/common/package.json ./shared/common/package.json
COPY --chown=node:node --from=builder /app/services/user-service/dist ./services/user-service/dist
COPY --chown=node:node --from=builder /app/services/user-service/package.json ./services/user-service/package.json

ENV NODE_ENV=production PORT=3001
WORKDIR /app/services/user-service
EXPOSE 3001

HEALTHCHECK --interval=15s --timeout=3s --start-period=15s --retries=3 \
  CMD node -e "require('http').get('http://localhost:3001/healthz',r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1))"

CMD ["node", "dist/server.js"]
