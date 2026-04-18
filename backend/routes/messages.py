from fastapi import APIRouter, Depends, Request
from uuid import UUID
from pydantic import BaseModel
from .auth import get_current_profile_id

router = APIRouter(prefix="/api/messages", tags=["messages"])

class SendMessage(BaseModel):
    content: str

@router.get("/conversations")
async def list_conversations(request: Request, profile_id: UUID=Depends(get_current_profile_id)):
    return []

@router.get("/conversations/{conv_id}")
async def get_messages(conv_id: UUID, request: Request=None, profile_id: UUID=Depends(get_current_profile_id)):
    return []

@router.post("/conversations/{conv_id}", status_code=201)
async def send_message(conv_id: UUID, body: SendMessage, request: Request=None, profile_id: UUID=Depends(get_current_profile_id)):
    return {"message_id": "demo"}