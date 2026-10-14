# Image for the edgible-mcp card: the mcp-bridge app card's Supergateway, with the Edgible CLI
# and the edgible-mcp stdio server added. Supergateway stays the entrypoint. The mcp-image
# workflow publishes it as ghcr.io/edgible-org/edgible-mcp:<version in package.json>.
FROM supercorp/supergateway:4.1.0-uvx

LABEL org.opencontainers.image.source=https://github.com/edgible-org/card-kit
LABEL org.opencontainers.image.description="Read-only Edgible MCP server, behind Supergateway"
LABEL org.opencontainers.image.licenses=MIT

# The CLI installer needs bash and curl, which the Alpine base lacks.
RUN apk add --no-cache bash curl

# The Edgible CLI, pinned. As root, the installer puts it in /opt/edgible-cli and /usr/local/bin.
ARG EDGIBLE_CLI_VERSION=1.4.6
RUN curl -fsSL https://get.edgible.com/install.sh \
    | EDGIBLE_CLI_VERSION=$EDGIBLE_CLI_VERSION EDGIBLE_SKIP_NODE=1 bash -s -- --yes \
 && edgible --version

# The server, as the command `edgible-mcp`, which the card's MCP_BRIDGE_COMMAND runs.
WORKDIR /opt/edgible-mcp
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund && npm cache clean --force
COPY server.mjs ./
RUN chmod 755 server.mjs && ln -s /opt/edgible-mcp/server.mjs /usr/local/bin/edgible-mcp

# HOME for the CLI's sign-in, the card's volume edgible-mcp-login. Only root reads it.
RUN mkdir -m 700 /login
WORKDIR /data
