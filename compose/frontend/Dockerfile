# Build custom Caddy binary with Coraza WAF plugin
FROM caddy:2.11.2-builder AS caddy
# Install CA certificates for Go module downloads; libcap for setcap
RUN apk add --no-cache ca-certificates libcap
RUN xcaddy build \
    --with github.com/corazawaf/coraza-caddy/v2
# Strip file capabilities here so the final image does not need libcap
RUN setcap -r /usr/bin/caddy

FROM alpine:3.23

RUN addgroup -S nonroot \
    && adduser -S nonroot -G nonroot

EXPOSE 8080

RUN apk add --no-cache \
    bash \
    curl \
    ca-certificates

COPY --from=caddy /build/caddy /usr/bin/caddy
COPY --chmod=755 ./compose/frontend/Caddyfile /Caddyfile
COPY ./compose/frontend/coraza.conf /etc/caddy/coraza.conf

# Create directories for Coraza WAF with restricted permissions
RUN mkdir -p /tmp/coraza && \
    chown -R 1001:0 /tmp/coraza && \
    chmod -R 770 /tmp/coraza

USER nonroot

CMD ["caddy", "run", "--config", "/Caddyfile"]