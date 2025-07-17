# Stage 1: build
FROM node:18 AS builder
WORKDIR /app
COPY app/ app/
RUN npm install
RUN npm run build

# Stage 2: serve with nginx
FROM nginx:alpine
# Create a non-root user
RUN addgroup -g 1001 nginxgroup && adduser -D -u 1001 -G nginxgroup nginxuser

# Update permissions for Nginx directories
RUN chown -R nginxuser:nginxgroup /var/cache/nginx /var/run /etc/nginx

# Switch to non-root user
USER nginxuser

COPY --from=builder /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
