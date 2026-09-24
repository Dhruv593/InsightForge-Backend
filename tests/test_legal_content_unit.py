import pytest
from pydantic import ValidationError

from app.schemas.site_content import LegalPagesContent
from app.services.site_content_service import DEFAULT_LEGAL_CONTENT


def test_default_legal_pages_are_complete_and_serializable():
    payload = DEFAULT_LEGAL_CONTENT.model_dump(mode="json")

    validated = LegalPagesContent.model_validate(payload)

    assert validated.privacy.title == "Privacy Policy"
    assert validated.terms.title == "Terms and Conditions"
    assert len(validated.privacy.sections) >= 1
    assert len(validated.terms.sections) >= 1


def test_legal_page_requires_content_for_both_documents():
    payload = DEFAULT_LEGAL_CONTENT.model_dump(mode="python")
    del payload["terms"]

    with pytest.raises(ValidationError):
        LegalPagesContent.model_validate(payload)


def test_legal_sections_cannot_publish_without_paragraphs():
    payload = DEFAULT_LEGAL_CONTENT.model_dump(mode="python")
    payload["privacy"]["sections"][0]["paragraphs"] = []

    with pytest.raises(ValidationError):
        LegalPagesContent.model_validate(payload)
