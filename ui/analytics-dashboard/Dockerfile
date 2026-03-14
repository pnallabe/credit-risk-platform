# syntax=docker/dockerfile:1
FROM node:20-alpine AS base

# ────────────────────────────────────────────────
# 1. Install dependencies only when needed
# ────────────────────────────────────────────────
FROM base AS deps
RUN apk add --no-cache libc6-compat
WORKDIR /app

COPY ui/analytics-dashboard/package.json ui/analytics-dashboard/package-lock.json* ./
RUN npm ci

# ────────────────────────────────────────────────
# 2. Build the application
# ────────────────────────────────────────────────
FROM base AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY ui/analytics-dashboard/ .

ENV NEXT_TELEMETRY_DISABLED=1

ARG NEXT_PUBLIC_DECISION_API_URL=http://localhost:8081
ARG NEXT_PUBLIC_AGENT_API_URL=http://localhost:8082
ENV NEXT_PUBLIC_DECISION_API_URL=${NEXT_PUBLIC_DECISION_API_URL}
ENV NEXT_PUBLIC_AGENT_API_URL=${NEXT_PUBLIC_AGENT_API_URL}

RUN npm run build

# ────────────────────────────────────────────────
# 3. Production image
# ────────────────────────────────────────────────
FROM base AS runner
WORKDIR /app

ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser  --system --uid 1001 nextjs

COPY --from=builder /app/public          ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static     ./.next/static

USER nextjs

EXPOSE 3001
ENV PORT=3001
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
