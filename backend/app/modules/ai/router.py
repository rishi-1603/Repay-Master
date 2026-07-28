from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import Optional
from app.modules.users.models import User
from app.core.dependencies import get_current_user
from app.modules.ai.service import get_ai_advice

class ChatRequest(BaseModel):
    message: str
    context: Optional[dict] = None

router = APIRouter()

@router.post("/chat")
def ai_chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    advice = get_ai_advice(request.message, request.context)
    return {"reply": advice}
