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
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8050"))

settings = Settings()
