#!/usr/bin/python3
# -*- coding: utf-8 -*-

import logging
import os

from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("JWT_SECRET", "jwt_secret")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 60))
RATE = os.getenv("RATE_LIMIT", "5/minute")

# DataBase configuration
DB_FILE = os.getenv("SQLITE_DB_FILE", "traffic.db")
DB_URL = f"sqlite+aiosqlite:///{DB_FILE}"  # f"sqlite:///{DB_FILE}"

# Proxy Settings
PROXY_SERVER = os.getenv("PLAYWRIGHT_PROXY_SERVER")
PROXY_BYPASS = os.getenv("PLAYWRIGHT_PROXY_BYPASS")
PROXY_USERNAME = os.getenv("PLAYWRIGHT_PROXY_USERNAME")
PROXY_PASSWORD = os.getenv("PLAYWRIGHT_PROXY_PASSWORD")

CONCURRENT_TABS = os.getenv(
    "CONCURRENT_TABS", 10
)  # Adjust based on your server capacity

# # Configure in config.py
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("traffic_api")
