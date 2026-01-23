FROM node:22-alpine AS builder

# Install bun
RUN apk add --no-cache curl bash
RUN curl -fsSL https://bun.sh/install | bash
ENV BUN_INSTALL=/root/.bun
ENV PATH=$BUN_INSTALL/bin:$PATH

WORKDIR /app

# Declare build arguments for environment variables
ARG VITE_API_BASE_URL
# Set as environment variable for build process
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

COPY package.json bun.lock ./
RUN bun install
COPY . .

# Remove any .env files to ensure Railway variables are used
RUN rm -f .env .env.* || true

RUN bun run build

FROM nginx:alpine
COPY --from=builder /app/build/client /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
