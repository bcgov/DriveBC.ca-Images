FROM alpine:3.22

RUN addgroup -S nonroot \
    && adduser -S nonroot -G nonroot

EXPOSE 8080

RUN apk add --no-cache \
    caddy \
    bash \
    curl

COPY --chmod=755 ./compose/frontend/Caddyfile /Caddyfile

USER nonroot

CMD ["caddy", "run", "--config", "/Caddyfile"]