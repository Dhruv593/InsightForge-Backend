from app.core.tracing import traced

import asyncio
import json
import logging
from time import perf_counter

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from app.schemas.llm import LLMMessage, LLMResult, LLMUsage
from app.services.llm.base import BaseLLMProvider, LLMProviderError

logger = logging.getLogger(__name__)


class GeminiProvider(BaseLLMProvider):
    provider_name = "gemini"

    @traced("gemini.structured", run_type="llm")
    async def generate_structured(
        self,
        *,
        messages: list[LLMMessage],
        response_model: type[BaseModel],
    ) -> LLMResult:
        client = genai.Client(api_key=self.api_key)
        async_client = client.aio
        started = perf_counter()
        try:
            system_instruction = "\n\n".join(
                message.content for message in messages if message.role == "system"
            ) or None
            contents = [
                types.Content(
                    role="model" if message.role == "assistant" else "user",
                    parts=[types.Part.from_text(text=message.content)],
                )
                for message in messages
                if message.role != "system"
            ]
            async with asyncio.timeout(self.timeout_seconds):
                response = await async_client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_json_schema=self._build_gemini_schema(response_model),
                    ),
                )
            validated = self._validate_response(response, response_model)
            usage_metadata = getattr(response, "usage_metadata", None)
            return LLMResult(
                provider="gemini",
                model=self.model_name,
                content=validated.model_dump(mode="json"),
                usage=LLMUsage(
                    prompt_tokens=getattr(usage_metadata, "prompt_token_count", None),
                    completion_tokens=getattr(
                        usage_metadata,
                        "candidates_token_count",
                        None,
                    ),
                    total_tokens=getattr(usage_metadata, "total_token_count", None),
                ),
                latency_ms=round((perf_counter() - started) * 1000),
            )
        except TimeoutError as exc:
            raise LLMProviderError("LLM_TIMEOUT", "The LLM request timed out.") from exc
        except errors.ClientError as exc:
            status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            logger.warning(
                "Gemini client request failed model=%s status_code=%s error_type=%s",
                self.model_name,
                status_code,
                type(exc).__name__,
            )
            if status_code in {401, 403}:
                raise LLMProviderError(
                    "LLM_AUTHENTICATION_FAILED",
                    "The selected LLM provider could not authenticate the request.",
                ) from exc
            if status_code == 429:
                raise LLMProviderError(
                    "LLM_RATE_LIMITED",
                    "The selected LLM provider is temporarily rate limited.",
                ) from exc
            raise LLMProviderError(
                "LLM_EXECUTION_FAILED",
                "The selected LLM provider could not complete the request.",
            ) from exc
        except errors.ServerError as exc:
            logger.warning(
                "Gemini server request failed model=%s error_type=%s",
                self.model_name,
                type(exc).__name__,
            )
            raise LLMProviderError(
                "LLM_PROVIDER_UNAVAILABLE",
                "The selected LLM provider is temporarily unavailable.",
            ) from exc
        except LLMProviderError:
            raise
        except ValidationError as exc:
            logger.warning(
                "Gemini structured response validation failed model=%s response_model=%s errors=%s",
                self.model_name,
                response_model.__name__,
                [{"location": list(error["loc"]), "type": error["type"]} for error in exc.errors()],
            )
            raise LLMProviderError(
                "LLM_INVALID_RESPONSE",
                "The selected LLM provider returned an invalid structured response.",
            ) from exc
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
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
                await async_client.aclose()
            except Exception:
                pass

    @traced("gemini.text", run_type="llm")
    async def generate_text(self, *, messages: list[LLMMessage]) -> LLMResult:
        client = genai.Client(api_key=self.api_key)
        async_client = client.aio
        started = perf_counter()
        try:
            system_instruction = "\n\n".join(message.content for message in messages if message.role == "system") or None
            contents = [
                types.Content(role="model" if message.role == "assistant" else "user", parts=[types.Part.from_text(text=message.content)])
                for message in messages if message.role != "system"
            ]
            async with asyncio.timeout(self.timeout_seconds):
                response = await async_client.models.generate_content(
                    model=self.model_name,
                    contents=contents,
                    config=types.GenerateContentConfig(system_instruction=system_instruction),
                )
            text = (getattr(response, "text", None) or "").strip()
            if not text:
                raise ValueError("Gemini response did not contain text.")
            usage_metadata = getattr(response, "usage_metadata", None)
            return LLMResult(
                provider="gemini", model=self.model_name, content={"text": text},
                usage=LLMUsage(
                    prompt_tokens=getattr(usage_metadata, "prompt_token_count", None),
                    completion_tokens=getattr(usage_metadata, "candidates_token_count", None),
                    total_tokens=getattr(usage_metadata, "total_token_count", None),
                ),
                latency_ms=round((perf_counter() - started) * 1000),
            )
        except TimeoutError as exc:
            raise LLMProviderError("LLM_TIMEOUT", "The LLM request timed out.") from exc
        except errors.ClientError as exc:
            status_code = getattr(exc, "status_code", None) or getattr(exc, "code", None)
            if status_code in {401, 403}:
                raise LLMProviderError("LLM_AUTHENTICATION_FAILED", "The selected LLM provider could not authenticate the request.") from exc
            if status_code == 429:
                raise LLMProviderError("LLM_RATE_LIMITED", "The selected LLM provider is temporarily rate limited.") from exc
            raise LLMProviderError("LLM_EXECUTION_FAILED", "The selected LLM provider could not complete the request.") from exc
        except errors.ServerError as exc:
            raise LLMProviderError("LLM_PROVIDER_UNAVAILABLE", "The selected LLM provider is temporarily unavailable.") from exc
        except LLMProviderError:
            raise
        except Exception as exc:
            raise LLMProviderError("LLM_EXECUTION_FAILED", "The selected LLM provider could not complete the request.") from exc
        finally:
            try:
                await async_client.aclose()
            except Exception:
                pass

    @staticmethod
    def _validate_response(response: object, response_model: type[BaseModel]) -> BaseModel:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, response_model):
            return parsed
        if parsed is not None:
            return response_model.model_validate(parsed)
        text = getattr(response, "text", None)
        if not text:
            raise ValueError("Gemini response did not contain structured content.")
        return response_model.model_validate(json.loads(text))

    @staticmethod
    def _build_gemini_schema(response_model: type[BaseModel]) -> dict[str, object]:
        """Flatten Pydantic JSON Schema to Gemini's supported structured-output subset."""
        source = response_model.model_json_schema()
        definitions = source.get("$defs", {})
        allowed_keys = {
            "type",
            "properties",
            "items",
            "enum",
            "description",
            "required",
            "anyOf",
        }

        def simplify(value: object) -> object:
            if isinstance(value, list):
                return [simplify(item) for item in value]
            if not isinstance(value, dict):
                return value
            if "$ref" in value:
                reference = str(value["$ref"])
                prefix = "#/$defs/"
                if not reference.startswith(prefix):
                    raise ValueError("Unsupported schema reference.")
                definition_name = reference.removeprefix(prefix)
                definition = definitions.get(definition_name)
                if definition is None:
                    raise ValueError("Schema reference could not be resolved.")
                return simplify(definition)

            simplified: dict[str, object] = {}
            if "const" in value:
                simplified["enum"] = [simplify(value["const"])]
            for key, item in value.items():
                if key not in allowed_keys:
                    continue
                if key == "properties" and isinstance(item, dict):
                    simplified[key] = {
                        name: simplify(schema) for name, schema in item.items()
                    }
                else:
                    simplified[key] = simplify(item)
            return simplified

        schema = simplify(source)
        if not isinstance(schema, dict):
            raise ValueError("Gemini response schema must be an object.")
        return schema
