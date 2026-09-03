"""`KnowledgeDocumentUpdateRequest` 源版本/人工译文版本二选一的契约校验。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.localization.locales import SupportedLocale
from app.schemas.knowledge import KnowledgeDocumentUpdateRequest


def test_source_version_edit_does_not_require_content_locale() -> None:
    request = KnowledgeDocumentUpdateRequest(content="新正文")

    assert request.is_source_version is True
    assert request.content_locale is None


def test_translation_edit_requires_content_locale() -> None:
    with pytest.raises(ValidationError) as error:
        KnowledgeDocumentUpdateRequest(content="English policy", is_source_version=False)

    assert "content_locale" in str(error.value)


def test_translation_edit_with_content_locale_is_accepted() -> None:
    request = KnowledgeDocumentUpdateRequest(
        content="English policy",
        is_source_version=False,
        content_locale=SupportedLocale.EN_US,
    )

    assert request.content_locale is SupportedLocale.EN_US
