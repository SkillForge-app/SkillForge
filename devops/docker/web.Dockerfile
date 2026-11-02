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
# Dev dependencies are kept: this is exactly what `npm run start` runs in Frontend's setup, and
# `next start` loads next.config.ts. A smaller image needs `output: "standalone"` from Frontend.
COPY --from=build /app/package.json /app/package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/apps/web/package.json /app/apps/web/next.config.ts apps/web/
COPY --from=build /app/apps/web/public apps/web/public
# Next writes its runtime cache under .next, so the app user owns it; everything else is read-only.
COPY --from=build --chown=node:node /app/apps/web/.next apps/web/.next
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
