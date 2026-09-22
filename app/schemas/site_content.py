from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=160)]
BodyText = Annotated[str, Field(min_length=1, max_length=1200)]
LongText = Annotated[str, Field(min_length=1, max_length=20000)]


def _safe_location(value: str) -> str:
    normalized = value.strip()
    if not normalized.startswith(("/", "#", "https://")):
        raise ValueError("Links and images must use an internal path, anchor, or HTTPS URL.")
    return normalized


class LinkContent(BaseModel):
    label: ShortText
    href: str = Field(min_length=1, max_length=500)

    _validate_href = field_validator("href")(_safe_location)


class HeroProcessItem(BaseModel):
    label: ShortText
    detail: ShortText


class HeroContent(BaseModel):
    enabled: bool = True
    title: ShortText
    accent: ShortText
    primary_action: LinkContent
    secondary_action: LinkContent
    process_items: list[HeroProcessItem] = Field(min_length=3, max_length=3)
    process_footer: ShortText


class NavigationContent(BaseModel):
    enabled: bool = True
    links: list[LinkContent] = Field(min_length=1, max_length=8)
    login_label: ShortText
    action: LinkContent


class TextCard(BaseModel):
    title: ShortText
    description: BodyText


class HowItWorksContent(BaseModel):
    enabled: bool = True
    title: ShortText
    accent: ShortText
    description: BodyText
    flow_labels: list[ShortText] = Field(min_length=3, max_length=3)
    cards: list[TextCard] = Field(min_length=3, max_length=3)


class PreviewStep(TextCard):
    image: str = Field(min_length=1, max_length=1000)
    alt: ShortText

    _validate_image = field_validator("image")(_safe_location)


class PreviewContent(BaseModel):
    enabled: bool = True
    title: ShortText
    accent: ShortText
    description: BodyText
    workspace_label: ShortText
    helper_text: ShortText
    open_label: ShortText
    steps: list[PreviewStep] = Field(min_length=3, max_length=3)


class PlatformContent(BaseModel):
    enabled: bool = True
    title: ShortText
    accent: ShortText
    description: BodyText
    action: LinkContent
    cards: list[TextCard] = Field(min_length=4, max_length=4)


class FaqItem(BaseModel):
    question: ShortText
    answer: BodyText


class FaqContent(BaseModel):
    enabled: bool = True
    title: ShortText
    accent: ShortText
    description: BodyText
    items: list[FaqItem] = Field(min_length=1, max_length=12)


class ClosingContent(BaseModel):
    enabled: bool = True
    title: ShortText
    action: LinkContent
    note: ShortText


class FooterContent(BaseModel):
    enabled: bool = True
    preview_link: LinkContent
    login_label: ShortText
    copyright_name: ShortText


class BlogSettings(BaseModel):
    enabled: bool = True


class LandingPageContent(BaseModel):
    navigation: NavigationContent
    hero: HeroContent
    how_it_works: HowItWorksContent
    preview: PreviewContent
    platform: PlatformContent
    faq: FaqContent
    closing: ClosingContent
    footer: FooterContent
    blog: BlogSettings = Field(default_factory=BlogSettings)


class LandingContentUpdate(BaseModel):
    content: LandingPageContent


class LandingContentResponse(BaseModel):
    content: LandingPageContent | None = None
    version: int = 0
    updated_at: datetime | None = None


class PlanItem(BaseModel):
    name: ShortText
    description: BodyText
    price_label: ShortText
    amount_paise: int = Field(default=0, ge=0, le=100_000_000)
    billing_label: ShortText
    credits: int = Field(ge=1, le=1000000)
    features: list[ShortText] = Field(min_length=1, max_length=12)
    button_label: ShortText
    button_href: str = Field(min_length=1, max_length=500)
    highlighted: bool = False

    _validate_button_href = field_validator("button_href")(_safe_location)


class PlansContent(BaseModel):
    enabled: bool = False
    title: ShortText
    description: BodyText
    note: ShortText
    plans: list[PlanItem] = Field(min_length=1, max_length=6)


class PlansContentUpdate(BaseModel):
    content: PlansContent


class PlansContentResponse(BaseModel):
    content: PlansContent
    version: int = 0
    updated_at: datetime | None = None


class ContentImageResponse(BaseModel):
    url: str
    public_id: str


class BlogSection(BaseModel):
    heading: ShortText
    body: LongText


class BlogContent(BaseModel):
    title: ShortText
    excerpt: BodyText
    author: ShortText = "Tatparya team"
    cover_image: str | None = Field(default=None, max_length=1000)
    cover_alt: str | None = Field(default=None, max_length=160)
    sections: list[BlogSection] = Field(min_length=1, max_length=30)

    @field_validator("cover_image")
    @classmethod
    def validate_cover_image(cls, value: str | None) -> str | None:
        return _safe_location(value) if value else None

    @model_validator(mode="after")
    def require_cover_alt(self):
        if self.cover_image and not (self.cover_alt or "").strip():
            raise ValueError("Cover image alt text is required when a cover image is provided.")
        return self


class BlogWriteRequest(BaseModel):
    slug: str = Field(min_length=3, max_length=160, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    status: Literal["draft", "published"] = "draft"
    content: BlogContent


class BlogSummaryResponse(BaseModel):
    slug: str
    status: str
    title: str
    excerpt: str
    author: str
    cover_image: str | None
    cover_alt: str | None
    version: int
    created_at: datetime
    updated_at: datetime


class BlogDetailResponse(BlogSummaryResponse):
    sections: list[BlogSection]


class BlogListResponse(BaseModel):
    items: list[BlogSummaryResponse]
    total: int
