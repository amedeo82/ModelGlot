# Web Tools

Status: implemented
Scope: `free-claude-code` on branch `custom/main`, aligned on 2026-11-17
Audience: users and maintainers

Free Claude Code (FCC) can execute the Anthropic server-tool shapes used by Claude Code:
`web_search_20250305` and forced `web_fetch_20250910`. The tools run locally in the FCC
process and return Anthropic-compatible server-tool blocks to the client.

## Supported requests

| Request shape | Support |
| --- | --- |
| Claude Code automatic `web_search_20250305` with the server tool as the only tool | Supported. |
| Client forces `web_search` with `tool_choice.type = "tool"` | Supported. |
| Client forces `web_fetch` with `tool_choice.type = "tool"` | Supported. |
| Automatic `web_fetch` | Not supported. |
| Mixed Anthropic server tool plus client-defined tools | Not supported. |
| Other Anthropic server-tool families or versions | Not supported. |

Unsupported shapes return a request error that identifies the unsupported request. FCC does
not silently forward an Anthropic server-tool request to a provider that cannot implement it.

Automatic web search translates the server-tool request into a hidden provider tool named
`fcc_web_search`. The upstream model proposes the search query, FCC performs the search, and
FCC converts the results back to Anthropic `server_tool_use` and
`web_search_tool_result` blocks.

## Configuration

The settings are available in **Admin UI → Model Config → Web Tools** and in the managed
environment file.

| Variable | Default | Effect |
| --- | --- | --- |
| `ENABLE_WEB_SERVER_TOOLS` | `true` | Enables local web server tools. |
| `WEB_FETCH_ALLOWED_SCHEMES` | `http,https` | Comma-separated URL schemes accepted by `web_fetch`. |
| `WEB_FETCH_ALLOW_PRIVATE_NETWORKS` | `false` | Allows private and loopback targets. Use only in a trusted lab environment. |

Example:

```dotenv
ENABLE_WEB_SERVER_TOOLS=true
WEB_FETCH_ALLOWED_SCHEMES=http,https
WEB_FETCH_ALLOW_PRIVATE_NETWORKS=false
```

Changing these values through the Admin UI applies them through the managed configuration.
The settings are read from the runtime configuration snapshot used by each request.

## Search controls

Claude Code can include `max_uses`, `allowed_domains`, or `blocked_domains` options on an
automatic web-search request. FCC rejects an invalid domain, an invalid `max_uses` value, or
a request that combines allowed and blocked domains.

Domain filters apply to the search results returned by FCC. They do not bypass the URL
egress policy for `web_fetch`.

## Fetch security

`web_fetch` is treated as user-controlled network input and is protected by an egress
policy:

- only configured URL schemes are accepted;
- `localhost`, `.localhost`, and `.local` hostnames are rejected;
- loopback, private, link-local, and other non-public IP targets are rejected by default;
- DNS results are resolved and validated before the connection;
- the connection remains pinned to the validated address set during redirects;
- redirects are bounded and every redirect target is validated again;
- response bodies and decoded fetch content are bounded.

`WEB_FETCH_ALLOW_PRIVATE_NETWORKS=true` removes the private-address restriction. It should
be enabled only for a controlled development environment where fetching internal services is
intentional.

## Failure behavior

A web-tool failure is returned as an Anthropic-compatible error block in the stream. FCC
logs the failure type and target host without logging credentials or raw response content.
If provider log settings explicitly enable raw payload logging, the normal privacy warning
applies.

Disabling `ENABLE_WEB_SERVER_TOOLS` does not silently disable a forced server tool. The
request fails with an error that names the disabled setting and tells the user to enable it
or remove the forced tool from the request.

## Verification

Focused tests cover request recognition, domain filters, egress policy, result conversion,
settings, and route behavior:

```bash
uv run pytest -q tests/application/test_web_tools.py tests/api/test_web_server_tools.py tests/runtime/test_web_tools_client.py
```

The Admin screenshot in the main README shows the current **Model Config → Web Tools**
controls.
