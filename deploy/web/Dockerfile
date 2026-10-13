# The front door: builds the CadastroAI interface and serves it with Caddy, alongside the API
# (proxied) and the optional desktop-installer download page.
FROM node:22-alpine AS build
WORKDIR /src
COPY desktop/package.json desktop/package-lock.json ./
RUN npm ci --ignore-scripts && npm rebuild esbuild
COPY desktop/ ./
RUN npx tsc --noEmit && npx vite build

FROM caddy:2.8-alpine
COPY --from=build /src/dist /srv/app
COPY deploy/download /srv/download
COPY deploy/Caddyfile /etc/caddy/Caddyfile
