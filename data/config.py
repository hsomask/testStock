import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BASE_DIR / ".env")

# 绕过系统代理，AkShare 访问东方财富等国内数据源不需要代理
os.environ["no_proxy"] = "*"
os.environ["NO_PROXY"] = "*"

import requests as _requests
_original_getproxies = _requests.utils.getproxies


def _getproxies_no_proxy():
    return {}


_requests.utils.getproxies = _getproxies_no_proxy

REPORT_DIR = BASE_DIR / "reports"

DATABASE_DSN = os.getenv("DATABASE_DSN", "")

PUSH_CHANNEL = os.getenv("PUSH_CHANNEL", "email")

FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", "")
FEISHU_SECRET = os.getenv("FEISHU_SECRET", "")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY", "")
MINIMAX_API_URL = "https://api.minimax.chat/v1/text/chatcompletion_v2"

# ── 账户过滤配置 ──
ALLOW_MAIN_BOARD = os.getenv("ALLOW_MAIN_BOARD", "true").lower() == "true"
ALLOW_CHINEXT = os.getenv("ALLOW_CHINEXT", "false").lower() == "true"
ALLOW_STAR = os.getenv("ALLOW_STAR", "false").lower() == "true"
ALLOW_BSE = os.getenv("ALLOW_BSE", "false").lower() == "true"
EXCLUDE_ST = os.getenv("EXCLUDE_ST", "true").lower() == "true"
MIN_PRICE = float(os.getenv("MIN_PRICE", "2"))
MAX_PRICE = float(os.getenv("MAX_PRICE", "200"))
MIN_AMOUNT = float(os.getenv("MIN_AMOUNT", "100000000"))
