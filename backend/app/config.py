from __future__ import annotations

import os
from pathlib import Path

APP_NAME = os.getenv("DEALPROOF_APP_NAME", "DealProof")
API_TITLE = os.getenv("DEALPROOF_API_TITLE", f"{APP_NAME} Backend")
HTTP_USER_AGENT = os.getenv("DEALPROOF_HTTP_USER_AGENT", f"{APP_NAME}/0.1 contact@dealproof.local")
AGENT_ROLE = os.getenv("DEALPROOF_AGENT_ROLE", "VC diligence red-team analyst")
DEFAULT_COMPANY = os.getenv("DEALPROOF_DEFAULT_COMPANY", "Untitled Deal")
DEFAULT_TAGLINE = os.getenv("DEALPROOF_DEFAULT_TAGLINE", "AI diligence target")
DEFAULT_STAGE = os.getenv("DEALPROOF_DEFAULT_STAGE", "Active diligence")
DATABASE_FILENAME = os.getenv("DEALPROOF_DATABASE_FILENAME", "dealproof.db")
EXPORT_MEMO_FILENAME = os.getenv("DEALPROOF_EXPORT_MEMO_FILENAME", "dealproof-red-team-memo.md")
LOCAL_RETRIEVAL_CITATION = os.getenv("DEALPROOF_LOCAL_RETRIEVAL_CITATION", f"{APP_NAME} local retrieval")
MEMO_TITLE = os.getenv("DEALPROOF_MEMO_TITLE", f"{APP_NAME} Red Team Memo")
ANALYSIS_COMPLETE_LABEL = os.getenv("DEALPROOF_ANALYSIS_COMPLETE_LABEL", "Analysis complete")
LOCAL_FRONTEND_ORIGINS = tuple(
    origin.strip()
    for origin in os.getenv("DEALPROOF_CORS_ORIGINS", "http://127.0.0.1:3000,http://localhost:3000").split(",")
    if origin.strip()
)
LOCAL_FRONTEND_ORIGIN_REGEX = os.getenv("DEALPROOF_CORS_ORIGIN_REGEX", r"http://(127\.0\.0\.1|localhost):\d+")
DEMO_PACKET_PATH = Path(os.getenv("DEALPROOF_DEMO_PACKET_PATH", Path(__file__).with_name("demo_packet.json")))
DEMO_PACKET_PATH_2 = Path(os.getenv("DEALPROOF_DEMO_PACKET_PATH_2", Path(__file__).with_name("synthpay_packet.json")))
ALLOWED_DEEPSEEK_MODELS = ("deepseek-v4-flash", "deepseek-v4-pro")
REQUESTED_DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
DEFAULT_DEEPSEEK_MODEL = REQUESTED_DEEPSEEK_MODEL if REQUESTED_DEEPSEEK_MODEL in ALLOWED_DEEPSEEK_MODELS else "deepseek-v4-flash"
DEFAULT_MAX_CLAIMS = int(os.getenv("DEALPROOF_MAX_CLAIMS", "5"))
DEFAULT_MAX_CLAIMS_PER_MATERIAL = int(os.getenv("DEALPROOF_MAX_CLAIMS_PER_MATERIAL", "6"))
DEFAULT_WEB_RESEARCH_ENABLED = os.getenv("DEALPROOF_WEB_SEARCH_ENABLED", "1").strip().lower() not in {"0", "false", "no"}
