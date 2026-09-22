from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile, status

from app.api.dependencies import (
    CurrentUser,
    get_dataset_profiling_service,
    get_dataset_service,
)
from app.schemas.dataset import (
    DatasetDeleteResponse,
    DatasetListResponse,
    DatasetResponse,
    DatasetPreviewResponse,
)
from app.schemas.dataset_profile import DatasetProfileResponse
from app.services.dataset_profiling_service import DatasetProfilingService
from app.services.dataset_service import DatasetService

router = APIRouter(prefix="/datasets", tags=["datasets"])


@router.post(
    "",
    response_model=DatasetResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_dataset(
    file: Annotated[UploadFile, File(description="Dataset file to upload")],
    user: CurrentUser,
    dataset_service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetResponse:
    dataset = await dataset_service.upload_dataset(file, user)
    return DatasetResponse.model_validate(dataset)


@router.get("", response_model=DatasetListResponse)
async def list_datasets(
    user: CurrentUser,
    dataset_service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetListResponse:
    datasets = await dataset_service.get_user_datasets(user)
    items = [DatasetResponse.model_validate(dataset) for dataset in datasets]
    return DatasetListResponse(items=items, total=len(items))


@router.get("/{dataset_id}", response_model=DatasetResponse)
async def get_dataset(
    dataset_id: UUID,
    user: CurrentUser,
    dataset_service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetResponse:
    dataset = await dataset_service.get_dataset(dataset_id, user)
    return DatasetResponse.model_validate(dataset)


@router.get("/{dataset_id}/preview", response_model=DatasetPreviewResponse)
async def preview_dataset(
    dataset_id: UUID,
    user: CurrentUser,
    dataset_service: Annotated[DatasetService, Depends(get_dataset_service)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DatasetPreviewResponse:
    return await dataset_service.get_preview(dataset_id, user, limit=limit, offset=offset)


@router.delete("/{dataset_id}", response_model=DatasetDeleteResponse)
async def delete_dataset(
    dataset_id: UUID,
    user: CurrentUser,
    dataset_service: Annotated[DatasetService, Depends(get_dataset_service)],
) -> DatasetDeleteResponse:
    await dataset_service.delete_dataset(dataset_id, user)
    return DatasetDeleteResponse()


@router.post("/{dataset_id}/profile", response_model=DatasetProfileResponse)
async def profile_dataset(
    dataset_id: UUID,
    user: CurrentUser,
    profiling_service: Annotated[
        DatasetProfilingService,
        Depends(get_dataset_profiling_service),
    ],
) -> DatasetProfileResponse:
    profile = await profiling_service.profile_dataset(dataset_id, user)
    return DatasetProfileResponse.model_validate(profile)


@router.get("/{dataset_id}/profile", response_model=DatasetProfileResponse)
async def get_dataset_profile(
    dataset_id: UUID,
    user: CurrentUser,
    profiling_service: Annotated[
        DatasetProfilingService,
        Depends(get_dataset_profiling_service),
    ],
) -> DatasetProfileResponse:
    profile = await profiling_service.get_profile(dataset_id, user)
    return DatasetProfileResponse.model_validate(profile)
