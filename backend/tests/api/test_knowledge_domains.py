"""业务域管理：建域建齐四板块、改名连带文档、删域的 recursive 保护。"""

from __future__ import annotations

from httpx import AsyncClient


async def test_create_domain_creates_all_four_sections(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/business-domains", json={"name": "新业务"}
    )

    assert response.status_code == 201
    assert [child["name"] for child in response.json()["children"]] == [
        "业务流程",
        "业务名词解释",
        "ddl",
        "指标或调用指标平台mcp的skill",
    ]


async def test_create_domain_rejects_reserved_name(admin_client: AsyncClient) -> None:
    response = await admin_client.post(
        "/api/admin/knowledge/business-domains", json={"name": "memory"}
    )

    assert response.status_code == 400


async def test_rename_moves_every_descendant_document(
    admin_client: AsyncClient, domain_with_document: dict[str, str]
) -> None:
    response = await admin_client.put(
        "/api/admin/knowledge/business-domains",
        params={"name": "旧域"},
        json={"new_name": "新域"},
        headers={"If-Match": f'"{domain_with_document["version"]}"'},
    )

    assert response.status_code == 200
    tree = (await admin_client.get("/api/admin/knowledge/tree")).json()
    business = next(root for root in tree["roots"] if root["path"] == "业务")
    assert [domain["name"] for domain in business["children"]] == ["新域"]


async def test_delete_non_empty_domain_without_recursive_returns_409(
    admin_client: AsyncClient, domain_with_document: dict[str, str]
) -> None:
    response = await admin_client.delete(
        "/api/admin/knowledge/business-domains",
        params={"name": "旧域"},
        headers={"If-Match": f'"{domain_with_document["version"]}"'},
    )

    assert response.status_code == 409
    assert response.json()["code"] == "WIKI_DIRECTORY_NOT_EMPTY"


async def test_delete_with_recursive_removes_documents(
    admin_client: AsyncClient, domain_with_document: dict[str, str]
) -> None:
    response = await admin_client.delete(
        "/api/admin/knowledge/business-domains",
        params={"name": "旧域", "recursive": "true"},
        headers={"If-Match": f'"{domain_with_document["version"]}"'},
    )

    assert response.status_code == 204
