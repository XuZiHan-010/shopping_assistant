"""resolve_client_ip 的可信代理跳数解析边界。"""

from __future__ import annotations

from fastapi import Request

from app.core.client_ip import resolve_client_ip


def _request(*, peer: str, forwarded_for: str | None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    scope = {
        "type": "http",
        "headers": headers,
        "client": (peer, 12345),
    }
    return Request(scope)


def test_ignores_forwarded_header_when_no_hops_trusted() -> None:
    request = _request(peer="203.0.113.5", forwarded_for="9.9.9.9")

    result = resolve_client_ip(request, trusted_proxy_hops=0, trusted_proxy_ips=frozenset())

    assert result == "203.0.113.5"


def test_takes_rightmost_trusted_hop_when_peer_is_trusted_proxy() -> None:
    request = _request(peer="10.0.0.1", forwarded_for="attacker-fake, 198.51.100.9")

    result = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "198.51.100.9"


def test_forged_prefixes_cannot_shift_the_trusted_hop() -> None:
    """伪造 XFF 前缀不能改变可信代理追加的右起跳数。"""

    honest = _request(peer="10.0.0.1", forwarded_for="198.51.100.9")
    forged = _request(
        peer="10.0.0.1",
        forwarded_for="9.9.9.9, 8.8.8.8, 7.7.7.7, 198.51.100.9",
    )

    kwargs = {"trusted_proxy_hops": 1, "trusted_proxy_ips": frozenset({"10.0.0.1"})}

    assert resolve_client_ip(honest, **kwargs) == "198.51.100.9"
    assert resolve_client_ip(forged, **kwargs) == "198.51.100.9"


def test_falls_back_to_peer_when_direct_peer_not_trusted() -> None:
    request = _request(peer="203.0.113.5", forwarded_for="198.51.100.9")

    result = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "203.0.113.5"


def test_falls_back_to_peer_when_chain_shorter_than_hops() -> None:
    request = _request(peer="10.0.0.1", forwarded_for="198.51.100.9")

    result = resolve_client_ip(
        request, trusted_proxy_hops=2, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "10.0.0.1"
