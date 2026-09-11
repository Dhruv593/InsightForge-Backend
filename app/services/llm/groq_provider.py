from app.core.tracing import traced

import asyncio
import json
from time import perf_counter

from groq import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncGroq,
    AuthenticationError,
    RateLimitError,
)
from pydantic import BaseModel, ValidationError

from app.schemas.llm import LLMMessage, LLMResult, LLMUsage
from app.services.llm.base import BaseLLMProvider, LLMProviderError


class GroqProvider(BaseLLMProvider):
    provider_name = "groq"

    @traced("groq.structured", run_type="llm")
    async def generate_structured(
        self,
        *,
        messages: list[LLMMessage],
        response_model: type[BaseModel],
    ) -> LLMResult:
        client = AsyncGroq(api_key=self.api_key, timeout=self.timeout_seconds)
        started = perf_counter()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                response = await client.chat.completions.create(
                    model=self.model_name,
                    messages=[message.model_dump() for message in messages],
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": response_model.__name__.lower(),
                            "strict": False,
                            "schema": response_model.model_json_schema(),
                        },
                    },
                )
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Groq response did not contain structured content.")
            validated = response_model.model_validate(json.loads(content))
            usage = getattr(response, "usage", None)
            return LLMResult(
                provider="groq",
                model=self.model_name,
                content=validated.model_dump(mode="json"),
                usage=LLMUsage(
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                ),
                latency_ms=round((perf_counter() - started) * 1000),
            )
        except (TimeoutError, APITimeoutError) as exc:
            raise LLMProviderError("LLM_TIMEOUT", "The LLM request timed out.") from exc
        except AuthenticationError as exc:
            raise LLMProviderError(
                "LLM_AUTHENTICATION_FAILED",
                "The selected LLM provider could not authenticate the request.",
            ) from exc
        except RateLimitError as exc:
            raise LLMProviderError(
                "LLM_RATE_LIMITED",
                "The selected LLM provider is temporarily rate limited.",
            ) from exc
        except APIConnectionError as exc:
            raise LLMProviderError(
                "LLM_PROVIDER_UNAVAILABLE",
                "The selected LLM provider is temporarily unavailable.",
            ) from exc
        except APIStatusError as exc:
            if exc.status_code >= 500:
                raise LLMProviderError(
                    "LLM_PROVIDER_UNAVAILABLE",
                    "The selected LLM provider is temporarily unavailable.",
                ) from exc
            raise LLMProviderError(
                "LLM_EXECUTION_FAILED",
                "The selected LLM provider could not complete the request.",
            ) from exc
        except LLMProviderError:
            raise
        except (json.JSONDecodeError, ValidationError, ValueError, TypeError) as exc:
            raise LLMProviderError(
                "LLM_INVALID_RESPONSE",
                "The selected LLM provider returned an invalid structured response.",
            ) from exc
        except Exception as exc:
            raise LLMProviderError(
                "LLM_EXECUTION_FAILED",
                "The selected LLM provider could not complete the request.",
            ) from exc
        finally:
            try:
                await client.close()
            except Exception:
                pass

    @traced("groq.text", run_type="llm")
    async def generate_text(self, *, messages: list[LLMMessage]) -> LLMResult:
        client = AsyncGroq(api_key=self.api_key, timeout=self.timeout_seconds)
        started = perf_counter()
        try:
            async with asyncio.timeout(self.timeout_seconds):
                response = await client.chat.completions.create(
                    model=self.model_name,
                    messages=[message.model_dump() for message in messages],
                )
            text = (response.choices[0].message.content or "").strip()
            if not text:
                raise ValueError("Groq response did not contain text.")
            usage = getattr(response, "usage", None)
            return LLMResult(
                provider="groq", model=self.model_name, content={"text": text},
                usage=LLMUsage(
                    prompt_tokens=getattr(usage, "prompt_tokens", None),
                    completion_tokens=getattr(usage, "completion_tokens", None),
                    total_tokens=getattr(usage, "total_tokens", None),
                ),
                latency_ms=round((perf_counter() - started) * 1000),
            )
        except (TimeoutError, APITimeoutError) as exc:
            raise LLMProviderError("LLM_TIMEOUT", "The LLM request timed out.") from exc
        except AuthenticationError as exc:
            raise LLMProviderError("LLM_AUTHENTICATION_FAILED", "The selected LLM provider could not authenticate the request.") from exc
        except RateLimitError as exc:
            raise LLMProviderError("LLM_RATE_LIMITED", "The selected LLM provider is temporarily rate limited.") from exc
        except APIConnectionError as exc:
            raise LLMProviderError("LLM_PROVIDER_UNAVAILABLE", "The selected LLM provider is temporarily unavailable.") from exc
        except APIStatusError as exc:
            code = "LLM_PROVIDER_UNAVAILABLE" if exc.status_code >= 500 else "LLM_EXECUTION_FAILED"
            message = "The selected LLM provider is temporarily unavailable." if exc.status_code >= 500 else "The selected LLM provider could not complete the request."
            raise LLMProviderError(code, message) from exc
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError("LLM_EXECUTION_FAILED", "The selected LLM provider could not complete the request.") from exc
        finally:
            try:
                await client.close()
            except Exception:
                pass
