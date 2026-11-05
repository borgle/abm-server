# Local mode
> 范围：开源单用户版 core。托管版的多用户、套餐、审批、计费不在本仓库。

Local mode runs the ABM server on `127.0.0.1`, so page content, API keys, files and video bytes stay on the user's machine.

## Start

```bash
docker compose -f docker-compose.yml -f docker-compose.local.yml up -d --build
```

Default URL:

```text
http://127.0.0.1:18050
```

The local compose file:

- binds only to localhost
- disables secure cookies because it uses HTTP
- logs email links instead of sending SMTP mail
- disables registration approval
- uses `ABM_QUOTA_ENFORCEMENT=soft`
- stores SQLite data in `./data`

Change the port with `ABM_PORT`.

## Connect the extension

1. Open `http://127.0.0.1:18050/console`.
2. Sign in with the bootstrap administrator from `docker-compose.local.yml`.
3. Create an API Key and click **Connect extension**.
4. Or open the extension settings and enter:
   - Server: `http://127.0.0.1:18050`
   - API Key: the key you created

## Connect an MCP client

Point the client at:

```text
http://127.0.0.1:18050/mcp
```

Examples:

```bash
claude mcp add --transport http abm http://127.0.0.1:18050/mcp
codex mcp add abm --url http://127.0.0.1:18050/mcp
codex mcp login abm
```

The first connection opens the local OAuth consent page.

## Security notes

- Local mode is intended for a single user on a trusted machine.
- Do not expose port `18050` to a LAN or the internet.
- Back up `./data/abm.db` if you care about the local account and API keys.
- Email links are printed to container logs; use `ABM_EMAIL_MODE=smtp` if you need real mail.
- Social login is disabled until you set `ABM_SOCIAL_*` client credentials. Google/GitHub/Microsoft can use localhost callbacks; WeChat and QQ require a registered public domain.
