import os

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-97e36d66bcf347e0ad6ed4772c64ba40")
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"

# Vision/OCR via SiliconFlow (DeepSeek-VL2)
SILICONFLOW_API_KEY = os.environ.get("SILICONFLOW_API_KEY", "")
SILICONFLOW_API_URL = "https://api.siliconflow.cn/v1/chat/completions"
VISION_MODEL = "deepseek-ai/DeepSeek-VL2"

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
MODEL_WEIGHTS_PATH = os.path.join(DATA_DIR, "model_weights.json")
BCB_DATA_PATH = os.path.join(DATA_DIR, "bcb_series.json")

FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
FLASK_DEBUG = False
