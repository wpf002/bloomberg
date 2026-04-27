# Multi-stage build: install deps + build a production bundle in one stage,
# then serve it from a tiny Vite preview server in the second. Local dev
# (docker-compose) used to use this image with `npm run dev`; Railway uses
# the same image but `npm run start` (vite preview) so the same artefact
# can ship to both. Local hot-reload is now a `npm run dev` outside Docker.
FROM node:20-alpine AS build

WORKDIR /app

# Install only with package.json (no lock copy) — matches the original
# image and keeps `npm install` resolving the latest compatible versions
# inside the container, mirroring what local dev gets.
COPY frontend/package.json ./package.json
RUN npm install

COPY frontend ./

# Cross-platform NODE_ENV=production so Tailwind purges and Vite minifies.
ENV NODE_ENV=production
RUN npm run build


FROM node:20-alpine AS runtime

WORKDIR /app

# Bring over node_modules + built dist + package.json. Vite preview only
# needs `vite` from devDependencies, which is included in node_modules.
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/package.json ./package.json
COPY --from=build /app/dist ./dist
COPY --from=build /app/vite.config.js ./vite.config.js

# Railway injects $PORT; default to 4173 (Vite preview default) so the
# image still runs under plain `docker run`.
ENV PORT=4173
EXPOSE 4173

CMD ["sh", "-c", "npm run start"]
