# edgible-mcp

An MCP server with read-only tools for Edgible. Every tool only reads; none changes anything.

- **find** searches the cards in [edgible-org/cards](https://github.com/edgible-org/cards) for a need described in plain words ("somewhere for my bookmarks", "Pocket shut down") or an app name. It returns the matching cards and the [needs map](../skills/edgible-cards/needs-map.yaml) entries: how well the need suits Edgible, the auth mode to publish with, what the machine needs, and the questions that change the answer.
- **describe** shows one card: its apps, images, ports, auth mode per hostname, minimum machine, test status, and its README's Why and What.
- **whats_running** lists the devices and published apps of the Edgible organization that the local Edgible CLI is signed in to. It checks that each https hostname answers the way its auth mode says, and for one app it adds `edgible app doctor`'s verdict. It needs the CLI signed in; find and describe do not.

It speaks MCP over stdio, and has no HTTP or auth code of its own. It fetches the cards and this repo from GitHub's main branch and caches them for 15 minutes (`EDGIBLE_MCP_CATALOG_TTL`, in seconds).

## Run it

On your own machine, with Node 20 or later, and for whats_running the `edgible` CLI, signed in with `edgible auth login`:

```bash
git clone https://github.com/edgible-org/card-kit ~/.card-kit
cd ~/.card-kit/edgible-mcp && npm ci --omit=dev
claude mcp add edgible -- node ~/.card-kit/edgible-mcp/server.mjs
```

For another MCP client, the command is `node <path>/server.mjs`.

To reach it from anywhere, run the [edgible-mcp card](https://github.com/edgible-org/cards/tree/main/edgible-mcp). It runs the image `ghcr.io/edgible-org/edgible-mcp` behind [mcp-bridge](https://github.com/edgible-org/cards/tree/main/mcp-bridge)'s Supergateway, published on Edgible's `api-key` auth. Anyone with a key sees the apps of the organization its CLI is signed in to, so sign that CLI in as an account that may see them.

## The image

[Dockerfile](Dockerfile) adds the pinned Edgible CLI and this server to `supercorp/supergateway:4.1.0-uvx`. The [mcp-image](../.github/workflows/mcp-image.yml) workflow builds it for amd64 and arm64 on every pull request that changes this directory, and on main publishes it as `ghcr.io/edgible-org/edgible-mcp:<version>`, from `package.json`. A published version is never replaced: a change raises the version in `package.json` and in `server.mjs`.
