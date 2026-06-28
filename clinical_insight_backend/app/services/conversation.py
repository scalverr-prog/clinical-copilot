"""
Conversational Clinical Reasoning Service

Handles multi-turn conversations where users can:
1. Present a case
2. Answer follow-up questions
3. Provide additional information
4. See how reasoning updates
"""

import time
from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
import httpx

from app.config import settings
from app.prompts.clinical_insight import CLINICAL_INSIGHT_SYSTEM_PROMPT


@dataclass
class ConversationMessage:
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Conversation:
    id: str
    messages: List[ConversationMessage] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)
    clinical_context: Dict = field(default_factory=dict)


class ConversationService:
    """Manages clinical reasoning conversations"""

    def __init__(self):
        self.conversations: Dict[str, Conversation] = {}

    def _get_enhanced_system_prompt(self) -> str:
        """Get the system prompt with conversation-specific additions"""
        return CLINICAL_INSIGHT_SYSTEM_PROMPT + """

## CONVERSATION MODE ADDITIONS

You are in a conversational mode. The user may:
1. Present a new case
2. Answer questions you asked
3. Provide additional information
4. Ask you to reconsider something

When the user provides answers to your decision questions:
- Explicitly state how the new information changes (or doesn't change) your assessment
- Update your confidence level if warranted
- Generate NEW decision questions based on the updated picture
- If a critical concern is ruled out, acknowledge it clearly
- If a concern is CONFIRMED, escalate its prominence

When the user adds information:
- Integrate it with what you already know
- Re-run your checks with the combined information
- Note if the new information resolves previous gaps or creates new ones

Always maintain context from the full conversation. Reference earlier information when relevant.

If you asked questions and the user didn't answer all of them, note which remain unanswered and why they still matter.
"""

    def _call_llm(self, messages: List[Dict[str, str]], system_prompt: str) -> str:
        """Call the configured LLM with conversation history - defaults to local Ollama"""
        if settings.llm_provider == "ollama":
            # Build prompt from conversation history
            prompt_parts = [system_prompt, ""]
            for msg in messages:
                role = "User" if msg["role"] == "user" else "Assistant"
                prompt_parts.append(f"{role}: {msg['content']}")
            prompt_parts.append("Assistant:")
            full_prompt = "\n\n".join(prompt_parts)

            url = f"{settings.ollama_base_url}/api/generate"
            payload = {
                "model": settings.ollama_model,
                "prompt": full_prompt,
                "stream": False,
            }
            with httpx.Client(timeout=120.0) as client:
                response = client.post(url, json=payload)
                response.raise_for_status()
                return response.json().get("response", "")

        elif settings.llm_provider == "anthropic" and settings.anthropic_api_key:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            response = client.messages.create(
                model=settings.model_name,
                max_tokens=4096,
                system=system_prompt,
                messages=messages,
            )
            return response.content[0].text

        elif settings.llm_provider == "openai" and settings.openai_api_key:
            import openai
            client = openai.OpenAI(api_key=settings.openai_api_key)
            full_messages = [{"role": "system", "content": system_prompt}] + messages
            response = client.chat.completions.create(
                model=settings.model_name,
                max_tokens=4096,
                messages=full_messages,
            )
            return response.choices[0].message.content

        else:
            raise ValueError(f"No valid LLM configured. Provider: {settings.llm_provider}")

    def create_conversation(self) -> str:
        """Create a new conversation and return its ID"""
        import uuid
        conv_id = str(uuid.uuid4())
        self.conversations[conv_id] = Conversation(id=conv_id)
        return conv_id

    def get_conversation(self, conv_id: str) -> Optional[Conversation]:
        """Get a conversation by ID"""
        return self.conversations.get(conv_id)

    def chat(self, conv_id: str, user_message: str) -> str:
        """
        Process a user message in a conversation.
        Returns the assistant's response.
        """
        # Get or create conversation
        if conv_id not in self.conversations:
            self.conversations[conv_id] = Conversation(id=conv_id)

        conv = self.conversations[conv_id]

        # Add user message
        conv.messages.append(ConversationMessage(role="user", content=user_message))

        # Build messages for LLM
        llm_messages = [
            {"role": msg.role, "content": msg.content}
            for msg in conv.messages
        ]

        # Call LLM
        response = self._call_llm(llm_messages, self._get_enhanced_system_prompt())

        # Add assistant response
        conv.messages.append(ConversationMessage(role="assistant", content=response))

        return response

    def get_history(self, conv_id: str) -> List[Dict]:
        """Get conversation history"""
        conv = self.conversations.get(conv_id)
        if not conv:
            return []
        return [
            {
                "role": msg.role,
                "content": msg.content,
                "timestamp": msg.timestamp.isoformat(),
            }
            for msg in conv.messages
        ]


# Singleton
conversation_service = ConversationService()
