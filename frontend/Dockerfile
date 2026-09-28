# Dev-oriented Dockerfile for the Vite frontend (hackathon demo stack).
#
# docker-compose.yml's `web` service bind-mounts ./frontend:/app plus an
# anonymous volume over /app/node_modules, i.e. this is meant to run the
# actual Vite dev server with hot reload, not a static production build.
# Running `vite dev` here keeps the /api proxy in vite.config.ts working
# exactly as it does outside Docker (proxies to http://localhost:8000,
# reachable because the `api` service is published on the host at :8000).
#
# node_modules is installed at image build time into /app/node_modules so
# that, once the anonymous volume in docker-compose.yml shadows the bind
# mount's (host, likely absent) node_modules, the container still has a
# populated one to run from.

FROM node:22-slim

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

EXPOSE 5173

# --host 0.0.0.0 so the dev server is reachable from outside the container
# (the compose file / host curl / demo browser), not just localhost inside it.
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
