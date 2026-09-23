from io import BytesIO
from typing import Annotated

from fastapi import APIRouter, Depends, File, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import AdminUser
from app.core.exceptions import AppError
from app.db.session import get_db_session
from app.email_templates import DEFAULT_EMAIL_TEMPLATES
from app.schemas.email_template import EmailTemplatesContent, EmailTemplatesResponse, EmailTemplatesUpdate, TEMPLATE_VARIABLES
from app.schemas.site_content import BlogContent, BlogDetailResponse, BlogListResponse, BlogSummaryResponse, BlogWriteRequest, ContentImageResponse, LandingContentResponse, LandingContentUpdate, LandingPageContent, PlansContent, PlansContentResponse, PlansContentUpdate
from app.services.cloudinary_service import CloudinaryService, CloudinaryUploadError
from app.services.site_content_service import DEFAULT_PLANS_CONTENT, SiteContentService

router = APIRouter(tags=["site-content"])
ALLOWED_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
MAX_CONTENT_IMAGE_BYTES = 5 * 1024 * 1024


def service(session: Annotated[AsyncSession, Depends(get_db_session)]) -> SiteContentService:
    return SiteContentService(session)


def _response(entry) -> LandingContentResponse:
    if entry is None:
        return LandingContentResponse()
    return LandingContentResponse(
        content=LandingPageContent.model_validate(entry.content),
        version=entry.version,
        updated_at=entry.updated_at,
    )


def _plans_response(entry) -> PlansContentResponse:
    if entry is None:
        return PlansContentResponse(content=DEFAULT_PLANS_CONTENT)
    return PlansContentResponse(content=PlansContent.model_validate(entry.content), version=entry.version, updated_at=entry.updated_at)


def _email_templates_response(entry) -> EmailTemplatesResponse:
    content = DEFAULT_EMAIL_TEMPLATES if entry is None else EmailTemplatesContent.model_validate(entry.content)
    return EmailTemplatesResponse(
        content=content,
        variables={name: list(values) for name, values in TEMPLATE_VARIABLES.items()},
        version=entry.version if entry is not None else 0,
        updated_at=entry.updated_at if entry is not None else None,
    )


def _blog_response(entry, *, detail: bool):
    content = BlogContent.model_validate(entry.content)
    values = dict(
        slug=entry.slug,
        status=entry.status,
        title=content.title,
        excerpt=content.excerpt,
        author=content.author,
        cover_image=content.cover_image,
        cover_alt=content.cover_alt,
        version=entry.version,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
    )
    if detail:
        return BlogDetailResponse(**values, sections=content.sections)
    return BlogSummaryResponse(**values)


async def _ensure_blog_enabled(content: SiteContentService) -> None:
    landing = await content.get_landing(published_only=True)
    if landing is not None and landing.content.get("blog", {}).get("enabled", True) is False:
        raise AppError("BLOG_DISABLED", "The blog is not currently available.", 404)


@router.get("/site-content/landing", response_model=LandingContentResponse)
async def public_landing(content: Annotated[SiteContentService, Depends(service)]) -> LandingContentResponse:
    return _response(await content.get_landing(published_only=True))


@router.get("/admin/site-content/landing", response_model=LandingContentResponse)
async def admin_landing(_: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> LandingContentResponse:
    return _response(await content.get_landing(published_only=False))


@router.put("/admin/site-content/landing", response_model=LandingContentResponse)
async def update_landing(payload: LandingContentUpdate, user: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> LandingContentResponse:
    return _response(await content.update_landing(payload.content, user))


@router.get("/site-content/plans", response_model=PlansContentResponse)
async def public_plans(content: Annotated[SiteContentService, Depends(service)]) -> PlansContentResponse:
    return _plans_response(await content.get_plans(published_only=True))


@router.get("/admin/site-content/plans", response_model=PlansContentResponse)
async def admin_plans(_: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> PlansContentResponse:
    return _plans_response(await content.get_plans(published_only=False))


@router.put("/admin/site-content/plans", response_model=PlansContentResponse)
async def update_plans(payload: PlansContentUpdate, user: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> PlansContentResponse:
    return _plans_response(await content.update_plans(payload.content, user))


@router.get("/admin/site-content/email-templates", response_model=EmailTemplatesResponse)
async def admin_email_templates(_: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> EmailTemplatesResponse:
    return _email_templates_response(await content.get_email_templates())


@router.put("/admin/site-content/email-templates", response_model=EmailTemplatesResponse)
async def update_email_templates(payload: EmailTemplatesUpdate, user: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> EmailTemplatesResponse:
    return _email_templates_response(await content.update_email_templates(payload.content, user))


@router.get("/blogs", response_model=BlogListResponse)
async def public_blogs(content: Annotated[SiteContentService, Depends(service)]) -> BlogListResponse:
    await _ensure_blog_enabled(content)
    entries = await content.list_blogs(published_only=True)
    return BlogListResponse(items=[_blog_response(entry, detail=False) for entry in entries], total=len(entries))


@router.get("/blogs/{slug}", response_model=BlogDetailResponse)
async def public_blog(slug: str, content: Annotated[SiteContentService, Depends(service)]) -> BlogDetailResponse:
    await _ensure_blog_enabled(content)
    return _blog_response(await content.get_blog(slug, published_only=True), detail=True)


@router.get("/admin/blogs", response_model=BlogListResponse)
async def admin_blogs(_: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> BlogListResponse:
    entries = await content.list_blogs(published_only=False)
    return BlogListResponse(items=[_blog_response(entry, detail=False) for entry in entries], total=len(entries))


@router.get("/admin/blogs/{slug}", response_model=BlogDetailResponse)
async def admin_blog(slug: str, _: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> BlogDetailResponse:
    return _blog_response(await content.get_blog(slug, published_only=False), detail=True)


@router.post("/admin/blogs", response_model=BlogDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_blog(payload: BlogWriteRequest, user: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> BlogDetailResponse:
    return _blog_response(await content.save_blog(slug=payload.slug, status=payload.status, blog=payload.content, user=user), detail=True)


@router.put("/admin/blogs/{slug}", response_model=BlogDetailResponse)
async def update_blog(slug: str, payload: BlogWriteRequest, user: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> BlogDetailResponse:
    return _blog_response(await content.save_blog(slug=payload.slug, status=payload.status, blog=payload.content, user=user, original_slug=slug), detail=True)


@router.delete("/admin/blogs/{slug}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_blog(slug: str, user: AdminUser, content: Annotated[SiteContentService, Depends(service)]) -> Response:
    await content.delete_blog(slug, user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/admin/site-content/images", response_model=ContentImageResponse)
async def upload_content_image(user: AdminUser, image: Annotated[UploadFile, File()]) -> ContentImageResponse:
    del user
    if image.content_type not in ALLOWED_IMAGE_TYPES or not image.filename:
        raise AppError("INVALID_CONTENT_IMAGE", "Upload a PNG, JPEG, WebP, or GIF image.", 415)
    data = await image.read(MAX_CONTENT_IMAGE_BYTES + 1)
    await image.close()
    if not data or len(data) > MAX_CONTENT_IMAGE_BYTES:
        raise AppError("CONTENT_IMAGE_TOO_LARGE", "Content images must be smaller than 5 MB.", 413)
    try:
        result = await CloudinaryService().upload_content_image(file_object=BytesIO(data), file_name=image.filename)
    except CloudinaryUploadError as exc:
        raise AppError("CONTENT_IMAGE_UPLOAD_FAILED", "The image could not be uploaded.", 502) from exc
    return ContentImageResponse(url=result.secure_url, public_id=result.public_id)
