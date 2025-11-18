import os
import asyncio
from typing import Optional, Awaitable, Callable

import requests
import google.generativeai as genai
from dotenv import load_dotenv


load_dotenv()


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
OPENROUTER_SITE_URL = os.getenv("OPENROUTER_SITE_URL", "https://zerofake.local")
OPENROUTER_APP_NAME = os.getenv("OPENROUTER_APP_NAME", "ZeroFake Fact Checker")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")


class ModelClientError(RuntimeError):
    """Base error for model client utilities."""


class RateLimitError(ModelClientError):
    """Raised when a provider returns a 429 response."""


async def call_gemini_model(
    model_name: str,
    prompt: str,
    *,
    timeout: Optional[float] = 30.0,
    safety_settings: Optional[list] = None,
    enable_browse: bool = False,
) -> str:
    """Call a Gemini model and return the raw text response."""
    if not GEMINI_API_KEY:
        raise ModelClientError("GEMINI_API_KEY is not configured.")

    genai.configure(api_key=GEMINI_API_KEY)
    model_kwargs = {}
    # Chỉ enable browse cho các model hỗ trợ (không phải tất cả Gemini models đều hỗ trợ)
    # googleSearchRetrieval chỉ hoạt động với một số model cụ thể
    if enable_browse:
        # Chỉ enable cho các model được biết là hỗ trợ
        browse_supported_models = ["gemini-1.5-pro", "gemini-pro"]
        model_name_clean = model_name.replace("models/", "").lower()
        if any(supported in model_name_clean for supported in browse_supported_models):
            model_kwargs["tools"] = [{"googleSearchRetrieval": {}}]
            print(f"Gemini Client: enabling built-in browse for model '{model_name}'.")
        else:
            print(f"Gemini Client: browse not supported for '{model_name}', skipping.")
    model = genai.GenerativeModel(model_name, **model_kwargs)

    def _generate():
        if safety_settings is not None:
            return model.generate_content(prompt, safety_settings=safety_settings)
        return model.generate_content(prompt)

    try:
        if timeout is None:
            response = await asyncio.to_thread(_generate)
        else:
            response = await asyncio.wait_for(asyncio.to_thread(_generate), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise ModelClientError(f"Gemini model '{model_name}' timed out after {timeout} seconds.") from exc
    except Exception as exc:  # noqa: BLE001
        raise ModelClientError(f"Gemini model '{model_name}' failed: {exc}") from exc

    text = getattr(response, "text", None)
    if not text and hasattr(response, "candidates") and response.candidates:
        text = str(response.candidates[0].content)
    if not text:
        raise ModelClientError(f"Gemini model '{model_name}' returned empty response.")
    return text


async def call_openai_chat_completion(
    model_name: str,
    prompt: str,
    *,
    timeout: float = 60.0,
    temperature: float = 0.2,
    system_prompt: Optional[str] = None,
) -> str:
    """Call OpenAI-compatible chat completion endpoint and return the message content."""
    if not OPENAI_API_KEY:
        raise ModelClientError("OPENAI_API_KEY is not configured.")

    base_url = OPENAI_BASE_URL.rstrip("/")
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model_name,
        "messages": [],
        "temperature": temperature,
        "stream": False,
    }
    if system_prompt:
        payload["messages"].append({"role": "system", "content": system_prompt})
    payload["messages"].append({"role": "user", "content": prompt})

    def _post():
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ModelClientError(f"OpenAI model '{model_name}' returned no choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if not content:
            raise ModelClientError(f"OpenAI model '{model_name}' returned empty content.")
        return content

    try:
        return await asyncio.to_thread(_post)
    except requests.RequestException as exc:
        raise ModelClientError(f"OpenAI model '{model_name}' request failed: {exc}") from exc


async def call_openrouter_chat_completion(
    model_name: str,
    prompt: str,
    *,
    timeout: float = 60.0,
    temperature: float = 0.2,
    system_prompt: Optional[str] = None,
    max_retries: int = 2,
    backoff_seconds: float = 2.0,
) -> str:
    """
    Call OpenRouter chat completion API and return the assistant message content.
    Implements simple retry with exponential backoff on rate limiting.
    """
    if not OPENROUTER_API_KEY:
        raise ModelClientError("OPENROUTER_API_KEY is not configured.")

    url = f"{OPENROUTER_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": OPENROUTER_SITE_URL,
        "X-Title": OPENROUTER_APP_NAME,
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }

    def _post():
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        if response.status_code == 429:
            detail = response.text.strip()[:200]
            raise RateLimitError(
                f"OpenRouter model '{model_name}' hit the rate limit (429). "
                f"Details: {detail or 'No body provided.'}"
            )
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ModelClientError(f"OpenRouter model '{model_name}' returned no choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if not content:
            raise ModelClientError(f"OpenRouter model '{model_name}' returned empty content.")
        return content

    attempt = 0
    while attempt <= max_retries:
        try:
            return await asyncio.to_thread(_post)
        except RateLimitError as exc:
            if attempt >= max_retries:
                raise
            delay = backoff_seconds * (attempt + 1)
            print(
                f"OpenRouter client: rate limit for '{model_name}', retrying in {delay:.1f}s "
                f"(attempt {attempt + 1}/{max_retries + 1})"
            )
            await asyncio.sleep(delay)
            attempt += 1
        except requests.RequestException as exc:
            raise ModelClientError(f"OpenRouter model '{model_name}' request failed: {exc}") from exc
        except ModelClientError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ModelClientError(f"OpenRouter model '{model_name}' unexpected error: {exc}") from exc


async def call_groq_chat_completion(
    model_name: str,
    prompt: str,
    *,
    timeout: float = 60.0,
    temperature: float = 0.2,
    system_prompt: Optional[str] = None,
) -> str:
    """Call Groq's OpenAI-compatible chat completion endpoint."""
    if not GROQ_API_KEY:
        raise ModelClientError("GROQ_API_KEY is not configured.")

    url = f"{GROQ_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json",
    }
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})
    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "stream": False,
    }

    def _post():
        response = requests.post(url, headers=headers, json=payload, timeout=timeout)
        response.raise_for_status()
        data = response.json()
        choices = data.get("choices") or []
        if not choices:
            raise ModelClientError(f"Groq model '{model_name}' returned no choices.")
        message = choices[0].get("message", {})
        content = message.get("content")
        if not content:
            raise ModelClientError(f"Groq model '{model_name}' returned empty content.")
        return content

    try:
        return await asyncio.to_thread(_post)
    except requests.RequestException as exc:
        raise ModelClientError(f"Groq model '{model_name}' request failed: {exc}") from exc


async def call_compound_model(
    prompt: str,
    *,
    timeout: Optional[float] = 60.0,
    temperature: float = 0.2,
    system_prompt: Optional[str] = None,
) -> str:
    """
    Try multiple providers in sequence until one succeeds.

    The goal is to increase robustness for Agent 1 planning when users select
    the synthetic "groq/compound" option.
    """

    attempts: list[tuple[str, Callable[[], Awaitable[str]]]] = []

    if GROQ_API_KEY:
        async def _call_groq() -> str:
            return await call_groq_chat_completion(
                "llama-3.1-70b-versatile",
                prompt,
                timeout=timeout or 60.0,
                temperature=temperature,
                system_prompt=system_prompt,
            )
        attempts.append(("groq", _call_groq))

    if OPENROUTER_API_KEY:
        async def _call_openrouter() -> str:
            return await call_openrouter_chat_completion(
                "meta-llama/llama-3.1-70b-instruct",
                prompt,
                timeout=timeout or 60.0,
                temperature=temperature,
                system_prompt=system_prompt,
            )
        attempts.append(("openrouter", _call_openrouter))

    if GEMINI_API_KEY:
        async def _call_gemini() -> str:
            combined_prompt = prompt
            if system_prompt:
                combined_prompt = f"{system_prompt}\n\n{prompt}"
            return await call_gemini_model(
                "models/gemini-2.5-flash",
                combined_prompt,
                timeout=timeout,
            )
        attempts.append(("gemini", _call_gemini))

    if not attempts:
        raise ModelClientError("No model providers are configured for compound mode.")

    last_error: Optional[Exception] = None
    for provider_name, attempt in attempts:
        try:
            print(f"Model Clients: compound planner trying provider '{provider_name}'")
            return await attempt()
        except ModelClientError as exc:
            last_error = exc
            print(f"Model Clients: provider '{provider_name}' failed: {exc}")
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            print(f"Model Clients: provider '{provider_name}' unexpected error: {exc}")

    raise ModelClientError(f"Compound planner failed: {last_error}") from last_error

