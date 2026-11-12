FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf

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