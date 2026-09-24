import pytest
from pydantic import ValidationError

from app.api import site_content
from app.schemas.site_content import ContactContent, ContactRequest, DEFAULT_LANDING_SECTION_ORDER, LandingContentResponse, LandingPageContent, VideoContent


def test_tutorial_video_accepts_internal_or_https_media_locations():
    assert VideoContent(video_url="/tutorial.mp4").video_url == "/tutorial.mp4"
    assert VideoContent(video_url="https://cdn.example.com/tutorial.webm").video_url.startswith("https://")

    with pytest.raises(ValidationError):
        VideoContent(video_url="http://example.com/tutorial.mp4")

    with pytest.raises(ValidationError):
        VideoContent(enabled=True)


def test_landing_section_defaults_place_faq_after_video():
    assert DEFAULT_LANDING_SECTION_ORDER.index("faq") == DEFAULT_LANDING_SECTION_ORDER.index("video") + 1
    assert VideoContent().theme == "light"

    with pytest.raises(ValidationError):
        VideoContent(theme="purple")


def test_contact_request_trims_content_and_rejects_empty_messages():
    request = ContactRequest(
        name="  Alex  ",
        email="alex@example.com",
        subject="  Product question  ",
        message="  Please tell me more.  ",
    )

    assert request.name == "Alex"
    assert request.subject == "Product question"
    assert request.message == "Please tell me more."

    with pytest.raises(ValidationError):
        ContactRequest(name="Alex", email="alex@example.com", subject="Hello", message="          ")

    without_subject = ContactRequest(name="Alex", email="alex@example.com", message="Please contact me.")
    assert without_subject.subject == ""


def test_public_landing_content_does_not_expose_contact_recipient(monkeypatch):
    contact = ContactContent(
        email="hello@tatparya.com",
        recipient_email="private-inbox@tatparya.com",
    )
    landing = LandingPageContent.model_construct(contact=contact)
    internal_response = LandingContentResponse.model_construct(content=landing, version=2, updated_at=None)
    monkeypatch.setattr(site_content, "_response", lambda _entry: internal_response)

    response = site_content._public_landing_response(object())

    assert response.content.contact.email == "hello@tatparya.com"
    assert str(response.content.contact.recipient_email) == "hello@tatparya.com"
