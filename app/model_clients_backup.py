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
        exc_str = str(exc).lower()
        # Detect quota exhausted / rate limit errors for immediate fallback
        if "429" in str(exc) or "quota" in exc_str or "resource_exhausted" in exc_str or "resourceexhausted" in exc_str:
            raise RateLimitError(f"Gemini model '{model_name}' quota exhausted (429): {exc}") from exc
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



async def call_groq_chat_completion(
    model_name: str,
    prompt: str,
    *,
    timeout: float = 60.0,
    temperature: float = 0.2,
    system_prompt: Optional[str] = None,
) -> str:
    """
    Call Groq's chat completion using official Groq SDK.
    Supports models like: llama-3.3-70b-versatile, openai/gpt-oss-120b, qwen/qwen3-32b
    """
    if not GROQ_API_KEY:
        raise ModelClientError("GROQ_API_KEY is not configured.")

    def _call_groq_sdk():
        try:
            from groq import Groq
            # Import Groq's rate limit error for proper 429 detection
            try:
                from groq import RateLimitError as GroqRateLimitError
            except ImportError:
                GroqRateLimitError = None
        except ImportError:
            raise ModelClientError("Groq SDK not installed. Run: pip install groq")
        
        client = Groq(api_key=GROQ_API_KEY)
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
            )
        except Exception as e:
            # Detect 429 rate limit from Groq SDK
            exc_str = str(e).lower()
            if GroqRateLimitError and isinstance(e, GroqRateLimitError):
                raise RateLimitError(f"Groq model '{model_name}' hit rate limit (429): {e}")
            if "429" in str(e) or "rate_limit" in exc_str or "quota" in exc_str:
                raise RateLimitError(f"Groq model '{model_name}' hit rate limit (429): {e}")
            raise  # Re-raise other exceptions
        
        if not completion.choices:
            raise ModelClientError(f"Groq model '{model_name}' returned no choices.")
        
        content = completion.choices[0].message.content
        if not content:
            raise ModelClientError(f"Groq model '{model_name}' returned empty content.")
        
        return content

    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_call_groq_sdk),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        raise ModelClientError(f"Groq model '{model_name}' request timed out after {timeout}s")
    except RateLimitError:
        # FIX: RateLimitError nên được re-raise trực tiếp, không wrap
        raise
    except ModelClientError:
        # Các lỗi từ bên trong _call_groq_sdk (như Groq SDK not installed)
        raise
    except Exception as exc:
        # Lỗi không xác định - wrap thành ModelClientError
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


# ==============================================================================
# MULTI-AGENT COUNCIL: CAPABILITY MATRIX AND FALLBACK LOGIC
# ==============================================================================

# MA TRẬN PHÂN VAI (AGENT ROSTER) - NUCLEAR UPGRADE
# High-Level Cognitive Concepts: Bayesian Inference, Logical Fallacy Detection, Lateral Thinking
# JUDGE: Thẩm phán Tối cao - Suy diễn Bayes & Cân chỉnh sắc thái
# CRITIC: Biện lý Đối lập - Phát hiện ngụy biện logic  
# PLANNER: Chiến lược gia Tình báo - Tư duy đa chiều & Định vị thông tin
AGENT_ROSTER = {
    "JUDGE": [
        "llama-3.3-70b-versatile",       # ƯU TIÊN 1: Llama 3.3 70B (Groq) - Complex Nuance Handling
        "models/gemma-3-27b-it",         # DỰ PHÒNG 1: Gemma 27B (Google) - Epistemic Uncertainty Expert
        "llama-3.1-70b-versatile",       # DỰ PHÒNG 2: Llama 3.1 70B (Groq) - Solid backup
        "openai/gpt-oss-120b"            # DỰ PHÒNG 3: GPT-OSS 120B (Groq) - Bayesian Inference Master
    ],
    "CRITIC": [
        "qwen/qwen3-32b",                # ƯU TIÊN 1: Qwen 32B (Groq) - Logical Fallacy Detection Master
        "models/gemma-3-27b-it",         # DỰ PHÒNG 1: Gemma 27B (Google) - Strong logic analysis
        "meta-llama/llama-4-scout-17b-16e-instruct",  # DỰ PHÒNG 2: Llama 4 Scout 17B (Groq)
        "openai/gpt-oss-20b"             # DỰ PHÒNG 3: GPT-OSS 20B (Groq) - Fast fallback
    ],
    "PLANNER": [
        "models/gemma-3-12b-it",         # ƯU TIÊN 1: Gemma 12B (Google) - Lateral Thinking Expert
        "llama-3.1-8b-instant",          # DỰ PHÒNG 1: Llama 8B (Groq) - Information Triangulation
        "compound-beta",                 # DỰ PHÒNG 2: Compound Beta (Groq) - Multi-provider resilience
        "compound-beta-mini"             # DỰ PHÒNG 3: Compound Mini (Groq) - Ultra-fast fallback
    ],
}


async def call_agent_with_capability_fallback(
    role: str,
    prompt: str,
    system_prompt: Optional[str] = None,
    temperature: float = 0.2,
    timeout: float = 90.0,
    **kwargs
) -> str:
    """
    Hàm gọi Agent thông minh với cơ chế Fallback dựa trên Năng lực.
    Tự động định tuyến (Routing) sang API phù hợp (Google/Groq).
    
    Args:
        role: Vai trò của agent (JUDGE, CRITIC, PLANNER)
        prompt: Nội dung prompt
        system_prompt: System prompt (optional)
        temperature: Nhiệt độ sinh text
        timeout: Thời gian chờ tối đa
    
    Returns:
        str: Kết quả từ model
    """
    role_key = role.upper()
    # Lấy danh sách model cho vai trò này, mặc định dùng Gemini Flash nếu không tìm thấy
    candidate_models = AGENT_ROSTER.get(role_key, ["models/gemini-2.5-flash"])
    
    errors = []
    print(f"\n[ORCHESTRATOR] Kich hoat Agent: {role_key}")
    
    # Vòng lặp thử từng model trong danh sách ưu tiên
    for i, model_name in enumerate(candidate_models):
        priority_label = "PRIMARY (MẠNH NHẤT)" if i == 0 else f"FALLBACK {i}"
        print(f"  --> [{priority_label}] Thu model: {model_name}...", end=" ")
        
        try:
            response_text = ""
            
            # --- LOGIC ĐỊNH TUYẾN (ROUTING) ---
            
            # 1. Nhóm Google (Gemma/Gemini) -> Gọi qua Gemini API
            if "gemma" in model_name.lower() or "gemini" in model_name.lower():
                # Google thường gộp system prompt vào prompt chính
                full_prompt = f"{system_prompt}\n\n{prompt}" if system_prompt else prompt
                response_text = await call_gemini_model(
                    model_name, 
                    full_prompt, 
                    timeout=timeout
                )
                
            # 2. Nhóm Groq (Llama, Compound, GPT-OSS, Qwen, meta-llama) -> Gọi qua Groq API
            # Groq hỗ trợ: llama-3.x, llama-4, compound, gpt-oss, qwen/qwen3-32b
            elif any(x in model_name.lower() for x in [
                "llama-3", "llama-4", "compound", "groq", "gpt-oss", 
                "qwen", "meta-llama"
            ]):
                # Giữ nguyên model name (Groq SDK hỗ trợ format openai/gpt-oss-120b, qwen/qwen3-32b)
                response_text = await call_groq_chat_completion(
                    model_name,
                    prompt,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    timeout=timeout,
                )
            
            # 3. Model không được nhận diện - Raise error rõ ràng
            else:
                raise ModelClientError(
                    f"Model '{model_name}' không được hỗ trợ. "
                    f"Chỉ hỗ trợ: Gemini/Gemma (Google) và Llama/Qwen/GPT-OSS (Groq)."
                )
                
            # Nếu chạy đến đây là thành công
            print("OK")
            return response_text

        except RateLimitError as e:
            # 429/Quota Exhausted - Chuyển ngay lập tức sang model dự phòng, KHÔNG retry
            print(f"QUOTA HẾT (429)")
            print(f"      ⚠️  {str(e)[:100]}")
            print(f"      → Chuyển NGAY sang model dự phòng...")
            errors.append(f"{model_name}: RATE_LIMIT_429 - {str(e)[:80]}")
            continue  # Fallback ngay lập tức
            
        except Exception as e:
            print(f"FAILED")
            print(f"      Lỗi: {str(e)[:150]}...")
            errors.append(f"{model_name}: {str(e)}")
            continue  # Chuyển sang model tiếp theo trong danh sách ưu tiên
            
    # Nếu tất cả đều lỗi
    raise ModelClientError(
        f"CRITICAL FAILURE: Tất cả model cho vai trò {role_key} đều thất bại. Chi tiết: {errors}"
    )
