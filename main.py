import io
import re
import numpy as np
from PIL import Image
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

app = FastAPI(title="Strict Brand Auth & Market Valuation Engine", version="10.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class StrictAIEngine:
    def validate_serial_format(self, brand: str, model_number: str, serial_number: str) -> tuple[bool, str]:
        brand_upper = brand.upper()
        model_upper = model_number.strip().upper()
        serial_upper = serial_number.strip().upper()

        if "LOUIS" in brand_upper or "LV" in brand_upper:
            if serial_upper and not re.match(r'^[A-Z]{2}\d{4}$', serial_upper):
                return False, "ルイ・ヴィトンの製造番号規格（英字2桁+数字4桁）と形式が一致しません。"
        
        if "ROLEX" in brand_upper:
            if serial_upper and len(serial_upper) < 6:
                return False, "ロレックスのシリアル刻印桁数が不足しています。"
            if model_upper and not re.match(r'^\d{4,6}[A-Z]*$', model_upper):
                return False, "ロレックスのリファレンス（Ref.型番）形式と一致しません。"

        return True, "型番・シリアル規格と正常に合致しています。"

    def calculate_market_prices(self, brand: str, category: str, score: float, has_model: bool) -> dict:
        brand_upper = brand.upper()

        base_val = 120000
        if "ROLEX" in brand_upper:
            base_val = 1800000
        elif "HERMES" in brand_upper:
            base_val = 800000
        elif "CHANEL" in brand_upper:
            base_val = 450000
        elif "LOUIS" in brand_upper or "LV" in brand_upper:
            base_val = 160000

        if has_model:
            base_val = int(base_val * 1.1)

        condition_factor = max(0.2, score / 100.0)
        
        buy_store_min = int(base_val * condition_
