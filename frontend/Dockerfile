FROM node:20-alpine

WORKDIR /app

# Optional npm registry mirror (uncomment NPM_REGISTRY in .env for faster downloads in China)
ARG NPM_REGISTRY
RUN if [ -n "$NPM_REGISTRY" ]; then npm config set registry "$NPM_REGISTRY"; fi

COPY package*.json ./

# BuildKit cache mount avoids re-downloading unchanged deps
RUN --mount=type=cache,target=/root/.npm \
    npm install

COPY . .

EXPOSE 15173

CMD ["npm", "run", "dev"]
