FROM node:22.13-bookworm-slim AS dependencies

WORKDIR /app

ENV PNPM_HOME=/pnpm \
    PATH=/pnpm:$PATH

RUN corepack enable && corepack prepare pnpm@11.19.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM dependencies AS build

COPY . ./

ARG VITE_API_BASE_URL
ARG VITE_REQUIRE_API_URL=true

ENV VITE_API_BASE_URL=${VITE_API_BASE_URL} \
    VITE_REQUIRE_API_URL=${VITE_REQUIRE_API_URL}

RUN pnpm run build

FROM node:22.13-bookworm-slim AS runtime

WORKDIR /app

ENV NODE_ENV=production

COPY --from=build --chown=node:node /app/package.json ./
COPY --from=build --chown=node:node /app/node_modules ./node_modules
COPY --from=build --chown=node:node /app/dist ./dist

USER node

EXPOSE 3000

CMD ["./node_modules/.bin/vinext", "start", "--hostname", "0.0.0.0", "--port", "3000"]
