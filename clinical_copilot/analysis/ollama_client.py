"""Ollama client for local LLM inference."""

import json
import httpx
from typing import Optional, Generator
from pydantic import BaseModel

from ..config import settings


class LLMResponse(BaseModel):
    """Response from LLM."""
    content: str
    model: str
    done: bool
    total_duration: Optional[int] = None
    eval_count: Optional[int] = None


class OllamaClient:
    """Client for local Ollama LLM."""

    CLINICAL_SYSTEM_PROMPT = """You are a clinical safety net. ONLY alert on things you can DIRECTLY SEE in the text.

CRITICAL RULE: You must QUOTE the exact text that triggered your alert. If you cannot quote it, DO NOT alert.

FORMAT - MUST include [Source: "quoted text"]:
ALERT: [finding] - [action] [Source: "exact quote from text"]
WARNING: [finding] - [reasoning] [Source: "exact quote"]
SUGGESTION: [optimization] [Source: "exact quote"]

EXAMPLE:
If text contains "K: 5.9 mEq/L" and "lisinopril 10mg":
WARNING: Elevated K 5.9 on ACE inhibitor - monitor for hyperkalemia [Source: "K: 5.9" + "lisinopril 10mg"]

DO NOT:
- Make up findings not in the text
- Assume medications or labs exist without seeing them
- Alert on things you're guessing might be there

If you cannot quote specific text to support your alert: "No alerts."
"""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.ollama.base_url
        self.primary_model = settings.ollama.primary_model
        self.fallback_model = settings.ollama.fallback_model
        self.timeout = settings.ollama.timeout
        self._client = httpx.Client(timeout=self.timeout)

    def health_check(self) -> bool:
        """Check if Ollama is running."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags")
            return response.status_code == 200
        except httpx.RequestError:
            return False

    def list_models(self) -> list[str]:
        """List available models."""
        try:
            response = self._client.get(f"{self.base_url}/api/tags")
            response.raise_for_status()
            data = response.json()
            return [m["name"] for m in data.get("models", [])]
        except httpx.RequestError:
            return []

    def has_model(self, model_name: str) -> bool:
        """Check if a specific model is available."""
        models = self.list_models()
        return any(model_name in m for m in models)

    def get_available_model(self) -> Optional[str]:
        """Get the best available model."""
        if self.has_model(self.primary_model):
            return self.primary_model
        if self.has_model(self.fallback_model):
            return self.fallback_model
        # Try to find any llama model
        models = self.list_models()
        for model in models:
            if "llama" in model.lower():
                return model
        return models[0] if models else None

    def generate(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None,
        stream: bool = False
    ) -> LLMResponse:
        """Generate a response from the LLM."""
        model = model or self.get_available_model()
        if not model:
            raise RuntimeError("No Ollama models available")

        system = system or self.CLINICAL_SYSTEM_PROMPT

        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": stream,
        }

        try:
            response = self._client.post(
                f"{self.base_url}/api/generate",
                json=payload
            )
            response.raise_for_status()
            data = response.json()

            return LLMResponse(
                content=data.get("response", ""),
                model=model,
                done=data.get("done", True),
                total_duration=data.get("total_duration"),
                eval_count=data.get("eval_count"),
            )
        except httpx.RequestError as e:
            raise RuntimeError(f"Ollama request failed: {e}")

    def generate_stream(
        self,
        prompt: str,
        system: Optional[str] = None,
        model: Optional[str] = None
    ) -> Generator[str, None, None]:
        """Stream a response from the LLM."""
        model = model or self.get_available_model()
        if not model:
            raise RuntimeError("No Ollama models available")

        system = system or self.CLINICAL_SYSTEM_PROMPT

        payload = {
            "model": model,
            "prompt": prompt,
            "system": system,
            "stream": True,
        }

        try:
            with self._client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json=payload
            ) as response:
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        if "response" in data:
                            yield data["response"]
                        if data.get("done"):
                            break
        except httpx.RequestError as e:
            raise RuntimeError(f"Ollama stream failed: {e}")

    def analyze_clinical_content(
        self,
        screen_text: str,
        context: Optional[str] = None
    ) -> LLMResponse:
        """Analyze clinical content from screen capture."""
        prompt = f"""TEXT VISIBLE ON SCREEN:
---
{screen_text}
---
"""
        if context:
            prompt += f"""CONTEXT: {context}
"""

        prompt += """
Find clinical concerns. MUST quote the source text for each alert.

Format: LEVEL: [issue] [Source: "exact quote from text above"]

Example: WARNING: High potassium on ACE inhibitor [Source: "K 5.8" + "lisinopril"]

If you cannot quote specific text, respond: "No alerts."
"""

        return self.generate(prompt)

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
