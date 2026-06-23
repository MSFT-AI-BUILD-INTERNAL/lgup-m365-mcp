# syntax=docker/dockerfile:1

# ---- Build stage ----
FROM node:20-alpine AS build
WORKDIR /app

COPY package*.json ./
RUN npm install

COPY tsconfig.json ./
COPY src ./src
RUN npm run build

# ---- Runtime stage ----
FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=8080

COPY package*.json ./
RUN npm install --omit=dev && npm cache clean --force

COPY --from=build /app/dist ./dist

EXPOSE 8080
USER node
CMD ["node", "dist/index.js"]
