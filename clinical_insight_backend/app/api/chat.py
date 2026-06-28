from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional

from app.services.conversation import conversation_service

router = APIRouter(prefix="/api/chat", tags=["Chat"])


class ChatRequest(BaseModel):
    message: str
    conversation_id: Optional[str] = None


class ChatResponse(BaseModel):
    conversation_id: str
    response: str


class ConversationHistory(BaseModel):
    conversation_id: str
    messages: List[dict]


@router.post("/message", response_model=ChatResponse)
async def send_message(request: ChatRequest):
    """
    Send a message to the Clinical Insight Engine.

    If no conversation_id is provided, a new conversation is created.
    The conversation maintains context across messages.
    """
    try:
        # Create new conversation if needed
        conv_id = request.conversation_id
        if not conv_id:
            conv_id = conversation_service.create_conversation()

        # Get response
        response = conversation_service.chat(conv_id, request.message)

        return ChatResponse(conversation_id=conv_id, response=response)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/history/{conversation_id}", response_model=ConversationHistory)
async def get_history(conversation_id: str):
    """Get the full history of a conversation."""
    history = conversation_service.get_history(conversation_id)
    return ConversationHistory(conversation_id=conversation_id, messages=history)


@router.post("/new")
async def new_conversation():
    """Start a new conversation and return its ID."""
    conv_id = conversation_service.create_conversation()
    return {"conversation_id": conv_id}
