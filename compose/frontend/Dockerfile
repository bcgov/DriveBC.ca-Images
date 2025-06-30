FROM nginx:1.29-alpine-slim
EXPOSE 3000
RUN touch /run/nginx.pid

# Install curl
RUN apk add --no-cache curl

COPY ./compose/frontend/default.conf /etc/nginx/conf.d/default.conf

RUN chmod -R 777 /run /var/log/nginx /var/cache/nginx /etc/nginx/conf.d
COPY ./compose/frontend/entrypoint /docker-entrypoint.d/add_client_env.sh
RUN sed -i 's/\r$//g' /docker-entrypoint.d/add_client_env.sh && chmod +x /docker-entrypoint.d/add_client_env.sh