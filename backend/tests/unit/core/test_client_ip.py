"""resolve_client_ip 的可信代理跳数解析边界。"""

from __future__ import annotations

from fastapi import Request

from app.core.client_ip import resolve_client_ip


def _request(*, peer: str, forwarded_for: str | None = None, real_ip: str | None = None) -> Request:
    headers = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode()))
    if real_ip is not None:
        headers.append((b"x-real-ip", real_ip.encode()))
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


def test_resolves_client_ip_from_x_real_ip_when_forwarded_for_absent() -> None:
    request = _request(peer="10.0.0.1", real_ip="203.0.113.7")

    result = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "203.0.113.7"


def test_single_trusted_proxy_prefers_real_ip_over_client_supplied_forwarded_for() -> None:
    """单跳代理下 X-Real-IP 优先：平台每次覆写它，XFF 则可能是客户端原样带上来的。"""

    request = _request(peer="10.0.0.1", forwarded_for="198.51.100.9", real_ip="203.0.113.7")

    result = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "203.0.113.7"


def test_single_trusted_proxy_gives_forged_forwarded_for_one_bucket() -> None:
    """伪造 XFF 不能在单跳代理下换到不同的解析结果，否则限流桶可被无限刷新。"""

    kwargs = {"trusted_proxy_hops": 1, "trusted_proxy_ips": frozenset({"10.0.0.1"})}
    first = _request(peer="10.0.0.1", forwarded_for="1.1.1.1", real_ip="203.0.113.7")
    second = _request(peer="10.0.0.1", forwarded_for="2.2.2.2", real_ip="203.0.113.7")

    assert resolve_client_ip(first, **kwargs) == resolve_client_ip(second, **kwargs)


def test_multi_hop_chain_still_wins_over_real_ip() -> None:
    """跳数大于 1 是运维显式声明的多层代理，只有 XFF 能表达该链路。"""

    request = _request(
        peer="10.0.0.1",
        forwarded_for="198.51.100.9, 10.0.0.9",
        real_ip="203.0.113.7",
    )

    result = resolve_client_ip(
        request, trusted_proxy_hops=2, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "198.51.100.9"


def test_falls_back_to_peer_when_trusted_proxy_sets_neither_header() -> None:
    request = _request(peer="10.0.0.1")

    result = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "10.0.0.1"


def test_untrusted_peer_cannot_spoof_x_real_ip() -> None:
    request = _request(peer="198.51.100.9", real_ip="203.0.113.7")

    result = resolve_client_ip(
        request, trusted_proxy_hops=1, trusted_proxy_ips=frozenset({"10.0.0.1"})
    )

    assert result == "198.51.100.9"
