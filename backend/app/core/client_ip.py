"""仅在明确可信的代理链后解析客户端来源地址。"""

from fastapi import Request


def resolve_client_ip(
    request: Request, *, trusted_proxy_hops: int, trusted_proxy_ips: frozenset[str]
) -> str:
    """解析可信代理后的客户端 IP。

    仅当直连 peer 已被信任时才读取转发头。单跳代理若注入
    ``X-Real-IP``，优先使用它：Railway 每次覆写该头，而客户端可以自带
    ``X-Forwarded-For``。多跳代理仍使用满足跳数要求的 XFF 链；本地 Docker
    的单跳 XFF 路径在没有 ``X-Real-IP`` 时保留。两个头均不可用时返回 peer。
    """

    peer = request.client.host if request.client else "unknown"
    if trusted_proxy_hops <= 0 or (trusted_proxy_ips and peer not in trusted_proxy_ips):
        return peer
    real_ip = request.headers.get("x-real-ip")
    if trusted_proxy_hops == 1 and real_ip:
        return real_ip
    raw = request.headers.get("x-forwarded-for", "")
    chain = [item.strip() for item in raw.split(",") if item.strip()]
    if len(chain) >= trusted_proxy_hops:
        return chain[-trusted_proxy_hops]
    return real_ip or peer
