import os

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-97e36d66bcf347e0ad6ed4772c64ba40")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# Vision/OCR via LM Studio local accesible por Tailscale VPN
LM_STUDIO_API_URL = os.environ.get("LM_STUDIO_API_URL", "http://100.121.240.89:8084/api/v1/chat")
VISION_MODEL = os.environ.get("VISION_MODEL", "zai-org/glm-4.6v-flash")
FALLBACK_VISION_MODEL = os.environ.get("FALLBACK_VISION_MODEL", "glm-ocr")
MAX_OUTPUT_TOKENS = int(os.environ.get("MAX_OUTPUT_TOKENS", "2500"))

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
MODEL_WEIGHTS_PATH = os.path.join(DATA_DIR, "model_weights.json")
BCB_DATA_PATH = os.path.join(DATA_DIR, "bcb_series.json")
SCAN_STATS_PATH = os.path.join(DATA_DIR, "scan_stats.json")
DATABASE_PATH = os.path.join(DATA_DIR, "dr_billetes.db")

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
FLASK_DEBUG = False
