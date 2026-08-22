import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    app_name: str = "Autonomous Rescue Agent"
    version: str = "1.0.0"
    atrip_api_base: str = os.getenv("ATRIP_API_BASE", "https://sandbox.atriptech.com")
    atrip_ak: str = os.getenv("ATRIP_ACCESS_KEY_ID", "mock_ak_aihackathon048")
    atrip_sk: str = os.getenv("ATRIP_ACCESS_KEY_SECRET", "mock_sk_aihackathon048")
    use_mock_fallback: bool = os.getenv("USE_MOCK_FALLBACK", "true").lower() == "true"
    # Real Qwen LLM (OpenAI-compatible endpoints: ModelScope / Model Studio / OpenRouter)
    model_api_key: str = os.getenv("ALIBABA_MODEL_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    default_model: str = os.getenv("DEFAULT_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    # Real Atlas flight search via official atlas-flight CLI
    atlas_use_cli: bool = os.getenv("ATLAS_USE_CLI", "false").lower() == "true"
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8050"))

settings = Settings()
