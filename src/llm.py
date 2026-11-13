import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

DEFAULT_MODEL = "deepseek-flash"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"


def get_llm(model: str | None = None, temperature: float = 0.0) -> ChatOpenAI:
    """Shared DeepSeek Chat Completions client for routing and tool use."""
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing DEEPSEEK_API_KEY. Set it in the environment or local .env.")

    return ChatOpenAI(
        model=model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL,
        api_key=api_key,
        base_url=DEEPSEEK_BASE_URL,
        temperature=temperature,
        extra_body={"thinking": {"type": "disabled"}},
        use_responses_api=False,
        # The orchestrator owns retries; avoid nested SDK retry loops.
        max_retries=0,
        timeout=60.0,
    )


def extract_usage(ai_message) -> dict:
    """Pull token usage out of a LangChain AIMessage, if present."""
    meta = getattr(ai_message, "usage_metadata", None)
    if not meta:
        return {}
    return {
        "input_tokens": meta.get("input_tokens"),
        "output_tokens": meta.get("output_tokens"),
        "total_tokens": meta.get("total_tokens"),
    }
