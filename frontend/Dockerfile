# syntax=docker/dockerfile:1

# --- Dependencies -----------------------------------------------------------
FROM node:22-bookworm-slim AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund

# --- Build ------------------------------------------------------------------
FROM node:22-bookworm-slim AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .

# next.config.ts resolves its rewrites at build time, so the upstream service
# hostnames must be present while `next build` runs.
ARG INGESTION_API_URL=http://ingestion-api:8003
ARG AGENTIC_API_URL=http://agentic-reasoning:8002
ARG NEXT_PUBLIC_ORGANIZATION_NAME=Zellovest
ENV INGESTION_API_URL=$INGESTION_API_URL \
    AGENTIC_API_URL=$AGENTIC_API_URL \
    NEXT_PUBLIC_ORGANIZATION_NAME=$NEXT_PUBLIC_ORGANIZATION_NAME

RUN npm run build

# --- Runtime ----------------------------------------------------------------
FROM node:22-bookworm-slim AS runner
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.ts ./next.config.ts

EXPOSE 3000

CMD ["npm", "start"]
