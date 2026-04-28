import os
from dotenv import load_dotenv

from utils.path_tool import get_abs_path

load_dotenv(get_abs_path(".env"))

QWEN_KEY = os.getenv("QWEN_KEY")
QWEN_MODEL = os.getenv("QWEN_MODEL")
QWEN_URL = os.getenv("QWEN_URL")
ROUTER_MODEL = os.getenv("ROUTER_MODEL")

if __name__ == "__main__":
    print("QWEN_API_KEY:", QWEN_KEY)
