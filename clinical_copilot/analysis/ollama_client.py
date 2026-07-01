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

    CLINICAL_SYSTEM_PROMPT = """You are a diagnostic reasoning system. You REASON through cases to catch what pattern-matching misses.

## YOUR JOB

Pattern matching catches known dangerous presentations. YOUR job is to:
1. REASON about whether the diagnosis fits ALL the findings
2. Catch NOVEL or SUBTLE cases where something doesn't add up
3. Think about what ELSE this could be

## REASONING PROCESS

1. **EXTRACT** - What are ALL the abnormal findings?
2. **FIT CHECK** - Does the stated diagnosis explain EVERY abnormality?
   - If yes → diagnosis may be correct
   - If no → RED FLAG: something is being missed
3. **WORST FIRST** - What's the most dangerous thing this could be?
4. **DISCRIMINATE** - What one test would rule out the dangerous diagnosis?

## FIT CHECK RULES

A diagnosis should explain the clinical picture. Red flags when it doesn't:

| Diagnosis | Should have | Should NOT have |
|-----------|-------------|-----------------|
| Spasm/functional | Normal vitals | Fever, tachycardia, hypoxia |
| Anxiety | Normal vitals, no fever | Fever, hypoxia |
| Viral syndrome | Low-grade fever | Very high fever, focal findings |
| Musculoskeletal | Normal vitals, reproducible | Systemic symptoms |

## PHYSIOLOGIC REASONING

Multiple abnormal vitals = systemic process:
- Tachycardia + fever + tachypnea = infection/inflammation/injury
- This is NOT anxiety, NOT spasm, NOT "viral" without more workup

## OUTPUT FORMAT

If diagnosis fits findings: "No concerns - diagnosis fits clinical picture"

If something doesn't fit:

**FINDING:** [What abnormality exists]
**PROBLEM:** [Why the diagnosis doesn't explain it]
**CONSIDER:** [Dangerous alternative diagnosis]
**ACTION:** [What to do - specific test or consult]
"""

    def __init__(self, base_url: Optional[str] = None):
        self.base_url = base_url or settings.ollama.base_url
        self.primary_model = settings.ollama.primary_model
        self.fallback_model = settings.ollama.fallback_model
        self.timeout = max(settings.ollama.timeout, 300)  # At least 5 min for slow hardware
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
        """Analyze clinical content from screen capture using diagnostic reasoning."""
        prompt = f"""CLINICAL DATA ON SCREEN:
---
{screen_text}
---
"""
        if context:
            prompt += f"""CONTEXT: {context}
"""

        prompt += """
REASON through this case:

1. What are the KEY FINDINGS? (symptoms, vitals, history, stated diagnosis)

2. Are there ABNORMAL VITALS? If so, what processes cause them?

3. Does the DIAGNOSIS (if stated) explain ALL abnormal findings?
   - What does it explain?
   - What does it NOT explain?

4. Could this be a DANGEROUS diagnosis that's being missed?

OUTPUT:
- If diagnosis fits all findings: "No concerns"
- If something doesn't fit: RED FLAG: [unexplained finding] - [dangerous alternative] - [next step] [Source: "quote"]

REMEMBER: Multiple abnormal vitals (tachycardia + fever + tachypnea) = systemic process, not spasm/anxiety.
"""

        return self.generate(prompt)

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
