"""`POST /agent/chat` (backend phase-01 §3, §4)."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from fastapi import APIRouter, Depends

from iam_sentinel_backend.deps import get_chat_service, get_correlation_id, get_principal
from iam_sentinel_backend.envelope import ok
from iam_sentinel_backend.schemas.chat import ChatRequest

if TYPE_CHECKING:
    from iam_sentinel_backend.auth.principal import Principal
    from iam_sentinel_backend.services.chat_service import ChatService

router = APIRouter(tags=["chat"])


@router.post("/agent/chat")
async def ask_prime(
    request: ChatRequest,
    principal: Principal = Depends(get_principal),
    correlation_id: str = Depends(get_correlation_id),
    chat_service: ChatService = Depends(get_chat_service),
) -> dict[str, Any]:
    decision = await chat_service.ask_prime(
        request=request, principal=principal, correlation_id=correlation_id
    )
    return ok(decision)
