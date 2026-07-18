FROM node:20-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
# Baked in at build time — Vite inlines import.meta.env.VITE_API_BASE into
# the bundle, so this must be set as a Railway service variable before build.
ARG VITE_API_BASE
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

FROM node:20-slim
WORKDIR /app
RUN npm install -g serve
COPY --from=build /app/dist ./dist
EXPOSE 3000
CMD serve -s dist -l ${PORT:-3000}
