import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

class Settings(BaseModel):
    app_name: str = "Autonomous Rescue Agent"
    version: str = "1.0.0"
    # Real Qwen LLM (OpenAI-compatible endpoints: ModelScope / Model Studio / OpenRouter)
    model_api_key: str = os.getenv("ALIBABA_MODEL_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "")
    default_model: str = os.getenv("DEFAULT_MODEL", "Qwen/Qwen2.5-72B-Instruct")
    # Autonomous radar scan interval (seconds)
    radar_interval_seconds: int = int(os.getenv("RADAR_INTERVAL_SECONDS", "15"))
    # Proactive Telegram guardian (optional; simulated when unset)
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_live_test: bool = os.getenv("TELEGRAM_LIVE_TEST", "false").lower() == "true"
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8050"))
    # TravelCare v2 optional keys (empty default; active only when set in .env)
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    serper_api_key: str = os.getenv("SERPER_API_KEY", "")
    amadeus_api_key: str = os.getenv("AMADEUS_API_KEY", "")
    # Brain architecture flag: legacy | qwen_agent
    travelcare_brain: str = os.getenv("TRAVELCARE_BRAIN", "legacy").strip().lower()

    def __init__(self, **data):
        if "travelcare_brain" not in data:
            data["travelcare_brain"] = os.getenv("TRAVELCARE_BRAIN", "legacy").strip().lower()
        super().__init__(**data)
        valid_brains = {"legacy", "qwen_agent"}
        if self.travelcare_brain not in valid_brains:
            import logging
            logging.getLogger("config").warning(
                f"Unknown TRAVELCARE_BRAIN={self.travelcare_brain!r}; coercing to 'legacy'"
            )
            self.travelcare_brain = "legacy"

settings = Settings()

