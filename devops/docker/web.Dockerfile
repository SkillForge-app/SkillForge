# The web app image (OPS-03): Next.js from frontend/ (Frontend's code; this file is DevOps-owned).
# Build context: frontend/. Used by the `web` service in compose.yaml:
#   docker compose --profile web up -d --build
# web.Dockerfile.dockerignore (next to this file) decides what of frontend/ is sent to the build.
#
# NEXT_PUBLIC_API_BASE_URL is baked into the browser code at build time, so it is a build arg, and it
# is the URL the browser uses (a host URL such as http://localhost:8000, not a compose service name).
# Changing it means rebuilding the image.

# Node 24.21.0 (frontend/.nvmrc), Debian slim, pinned by digest (multi-arch index) to an image at
# least two weeks old. Keep it in step with frontend/.nvmrc.
ARG NODE_IMAGE=node:24.21.0-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20

# ---------------------------------------------------------------- dependencies (cached layer)
FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund

# ---------------------------------------------------------------- build
FROM deps AS build
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_TELEMETRY_DISABLED=1
COPY . .
RUN npm run build && rm -rf apps/web/.next/cache

# ---------------------------------------------------------------- runtime
FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
# Frontend builds with `output: "standalone"` (apps/web/next.config.ts): .next/standalone holds the
# server and only the node_modules it needs, laid out like frontend/. The standalone server does
# not serve .next/static or public/ unless they are copied next to it, so they are copied here.
COPY --from=build /app/apps/web/.next/standalone ./
COPY --from=build /app/apps/web/.next/static apps/web/.next/static
COPY --from=build /app/apps/web/public apps/web/public
# Next writes its runtime cache under .next/cache: only that is writable by the app user.
RUN mkdir -p apps/web/.next/cache && chown node:node apps/web/.next/cache
USER node
EXPOSE 3000
# The same server Frontend's `npm run start` launches (node .next/standalone/apps/web/server.js),
# run directly: the standalone output has no npm scripts. It reads PORT and HOSTNAME.
CMD ["node", "apps/web/server.js"]
