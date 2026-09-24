from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import TypeVar

from pydantic import BaseModel

from utils.config import Settings
from utils.errors import UserFacingError
from utils.logging import get_logger

logger = get_logger("clauselens.openai")

T = TypeVar("T", bound=BaseModel)


@dataclass
class LLMResult:
    parsed: BaseModel
    input_tokens: int
    output_tokens: int


class OpenAIService:
    """Single OpenAI client for every agent."""

    def __init__(self, settings: Settings):
        if not settings.api_key:
            raise UserFacingError(
                "OPENAI_API_KEY is missing. Add it to a .env file in the project folder and restart ClauseLens."
            )
        if not settings.model:
            raise UserFacingError(
                "OPENAI_MODEL is missing. Set it in .env to a model that supports structured outputs."
            )
        from openai import OpenAI

        self.model = settings.model
        self.chat_model = settings.chat_model or settings.model
        self._client = OpenAI(api_key=settings.api_key, timeout=120.0)

    def stream_text(self, *, agent: str, system: str, user: str, tracker, max_tokens: int = 600) -> Iterator[str]:
        """Stream a plain-text chat reply from the chat model and record its token usage."""
        from openai import APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError, RateLimitError

        kwargs = {
            "model": self.chat_model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        try:
            try:
                stream = self._client.chat.completions.create(**kwargs, temperature=0.4)
            except BadRequestError as exc:
                if "temperature" not in str(exc).lower():
                    raise
                stream = self._client.chat.completions.create(**kwargs)
            for chunk in stream:
                if chunk.usage:
                    tracker.record(agent, chunk.usage.prompt_tokens or 0, chunk.usage.completion_tokens or 0)
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except AuthenticationError as exc:
            logger.error("%s authentication failed", agent)
            raise UserFacingError("OpenAI rejected the API key. Check OPENAI_API_KEY and restart the app.") from exc
        except RateLimitError as exc:
            logger.error("%s rate limited", agent)
            raise UserFacingError("OpenAI rate-limited this request. Wait a moment and try again.") from exc
        except (APITimeoutError, APIConnectionError) as exc:
            logger.error("%s network failure: %s", agent, type(exc).__name__)
            raise UserFacingError("The OpenAI request timed out or could not connect. Check the network and try again.") from exc
        except BadRequestError as exc:
            logger.error("%s rejected the request: %s", agent, type(exc).__name__)
            raise UserFacingError(
                f"The chat model rejected the request. Check that OPENAI_CHAT_MODEL ({self.chat_model}) is a valid chat model."
            ) from exc
        except Exception as exc:
            logger.error("%s chat call failed: %s", agent, type(exc).__name__)
            raise UserFacingError("The chat service returned an unexpected error. Please try again.") from exc

    def parse(self, *, agent: str, system: str, user: str, response_model: type[T]) -> LLMResult:
        from openai import APIConnectionError, APITimeoutError, AuthenticationError, BadRequestError, RateLimitError

        try:
            completion = self._create(system, user, response_model, temperature=0)
        except BadRequestError as exc:
            if "temperature" in str(exc).lower():
                try:
                    completion = self._create(system, user, response_model, temperature=None)
                except BadRequestError as retry_exc:
                    logger.error("%s rejected the request: %s", agent, type(retry_exc).__name__)
                    raise UserFacingError(
                        "The model rejected the analysis request. Set OPENAI_MODEL to a model that supports structured outputs."
                    ) from retry_exc
            else:
                logger.error("%s rejected the request: %s", agent, type(exc).__name__)
                raise UserFacingError(
                    "The model rejected the analysis request. Set OPENAI_MODEL to a model that supports structured outputs."
                ) from exc
        except AuthenticationError as exc:
            logger.error("%s authentication failed", agent)
            raise UserFacingError(
                "OpenAI rejected the API key. Check OPENAI_API_KEY and restart the app."
            ) from exc
        except RateLimitError as exc:
            logger.error("%s rate limited", agent)
            raise UserFacingError(
                "OpenAI rate-limited this request. Wait a moment and run the analysis again."
            ) from exc
        except (APITimeoutError, APIConnectionError) as exc:
            logger.error("%s network failure: %s", agent, type(exc).__name__)
            raise UserFacingError(
                "The OpenAI request timed out or could not connect. Check the network and try again."
            ) from exc
        except Exception as exc:
            logger.error("%s model call failed: %s", agent, type(exc).__name__)
            raise UserFacingError(
                "The analysis service returned an unexpected error. No signing recommendation was produced."
            ) from exc

        parsed = completion.choices[0].message.parsed
        if parsed is None:
            raise UserFacingError(
                "The model returned a response that did not match the required structure. Run the analysis again."
            )
        usage = completion.usage
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or getattr(usage, "output_tokens", 0) or 0)
        return LLMResult(parsed=parsed, input_tokens=input_tokens, output_tokens=output_tokens)

    def _create(self, system: str, user: str, response_model: type[BaseModel], temperature: float | None):
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": response_model,
            "max_completion_tokens": 8000,
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        return self._client.chat.completions.parse(**kwargs)
