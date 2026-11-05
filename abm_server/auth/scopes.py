"""OAuth and MCP authorization scopes."""

BROWSER = "browser"
ACCOUNT_READ = "account:read"
ACCOUNT_WRITE = "account:write"

DEFAULT_SCOPES: tuple[str, ...] = (BROWSER, ACCOUNT_READ, ACCOUNT_WRITE)
ALL_SCOPES: tuple[str, ...] = DEFAULT_SCOPES
