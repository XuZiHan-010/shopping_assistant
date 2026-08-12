"""仅在明确可信的代理链后解析客户端来源地址。"""

from fastapi import Request


def resolve_client_ip(
    request: Request, *, trusted_proxy_hops: int, trusted_proxy_ips: frozenset[str]
) -> str:
    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0 or (trusted_proxy_ips and peer not in trusted_proxy_ips):
        return peer
    raw = request.headers.get("x-forwarded-for", "")
    chain = [item.strip() for item in raw.split(",") if item.strip()]
    if len(chain) < trusted_proxy_hops:
        return peer
    return chain[-trusted_proxy_hops]
