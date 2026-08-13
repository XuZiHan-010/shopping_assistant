"""仅在明确可信的代理链后解析客户端来源地址。"""

from fastapi import Request


def resolve_client_ip(
    request: Request, *, trusted_proxy_hops: int, trusted_proxy_ips: frozenset[str]
) -> str:
    """解析可信代理后的客户端 IP。

    仅当直连 peer 已被信任时才读取转发头。优先使用满足跳数要求的
    ``X-Forwarded-For``（保留多跳代理语义）；其缺失或跳数不足时，回落到
    Railway 单层代理注入的 ``X-Real-IP``。两个头均不可用时返回 peer。
    """

    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0 or (trusted_proxy_ips and peer not in trusted_proxy_ips):
        return peer
    raw = request.headers.get("x-forwarded-for", "")
    chain = [item.strip() for item in raw.split(",") if item.strip()]
    if len(chain) >= trusted_proxy_hops:
        return chain[-trusted_proxy_hops]
    return request.headers.get("x-real-ip", peer)
