"""The `LLMClient` port on the Gemini API, with an API key (prototype)."""

import httpx
from google import genai
from google.genai import errors, types

from dca.core.ports import LLMResult, LLMTransientError


def _retry_after(error: errors.APIError) -> float | None:
    response = getattr(error, "response", None)
    headers = getattr(response, "headers", None) or {}
    try:
        return float(headers.get("retry-after")) if headers.get("retry-after") else None
    except (TypeError, ValueError):
        return None


class GeminiLLMClient:
    def __init__(self, api_key: str, timeout_s: float) -> None:
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._client: genai.Client | None = None

    @property
    def client(self) -> genai.Client:
        if self._client is None:
            # One attempt only: our code does the backoff, so that the CLI can show it (P15).
            self._client = genai.Client(
                api_key=self.api_key or None,
                http_options=types.HttpOptions(
                    timeout=int(self.timeout_s * 1000), retry_options=types.HttpRetryOptions(attempts=1)
                ),
            )
        return self._client

    def generate(self, prompt: str, *, model: str, system: str = "", json_schema: dict | None = None) -> LLMResult:
        config = types.GenerateContentConfig(
            system_instruction=system or None,
            response_mime_type="application/json" if json_schema else None,
            response_json_schema=json_schema,
        )
        try:
            response = self.client.models.generate_content(model=model, contents=prompt, config=config)
        except errors.APIError as error:
            if error.code == 429 or (error.code or 0) >= 500:
                raise LLMTransientError(error.code, _retry_after(error)) from None
            raise
        except httpx.TimeoutException:
            raise LLMTransientError(504) from None
        usage = response.usage_metadata
        return LLMResult(
            text=response.text or "",
            tokens_in=(usage.prompt_token_count or 0) if usage else 0,
            tokens_out=(usage.candidates_token_count or 0) if usage else 0,
        )
