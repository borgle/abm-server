from fastapi import APIRouter

try:  # The hosted edition ships a private cloud package; the open-source tree omits it.
    from abm_cloud.api import api_router as cloud_router
except ImportError:  # pragma: no cover - single-user distribution
    cloud_router = None

from .routes import (
    admin,
    api_keys,
    auth,
    creation,
    creation_media,
    extension_ws,
    notices,
    runtime,
    usage,
    video,
)

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(api_keys.router)
api_router.include_router(admin.router)
if cloud_router is not None:
    api_router.include_router(cloud_router)
api_router.include_router(creation.router)
api_router.include_router(creation_media.router)
api_router.include_router(runtime.router)
api_router.include_router(notices.router)
api_router.include_router(usage.router)
api_router.include_router(extension_ws.router)
api_router.include_router(video.router)
