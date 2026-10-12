import io
import re
import sqlite3
import numpy as np
from PIL import Image
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

app = FastAPI(title="Growth AI Brand Authenticator Engine", version="15.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLite データベース初期化
DB_NAME = "ai_learning_data.db"

def init_sqlite_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS authentications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            brand TEXT,
            category TEXT,
            model_number TEXT,
            serial_number TEXT,
            score REAL,
            judgment TEXT,
            feature_hash REAL,
            user_verified INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

init_sqlite_db()

class GrowthAIEngine:
    def find_learned_model(self, brand: str, feature_hash: float) -> Optional[str]:
        """過去に学習された正解データから類似画像を検索"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT model_number FROM authentications
            WHERE brand = ? AND user_verified = 1 AND model_number != ''
            ORDER BY ABS(feature_hash - ?) ASC LIMIT 1
        ''', (brand, feature_hash))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None

    def save_record(self, brand: str, category: str, model_number: str, serial_number: str, score: float, judgment: str, feature_hash: float, is_verified: int = 0) -> int:
        """査定実績・学習データを保存"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO authentications (brand, category, model_number, serial_number, score, judgment, feature_hash, user_verified)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (brand, category, model_number, serial_number, score, judgment, feature_hash, is_verified))
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return record_id

    def update_feedback(self, record_id: int, correct_model: str):
        """ユーザーからの正解データフィードバックを学習"""
        conn = sqlite3.connect(DB_NAME)
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE authentications
            SET model_number = ?, user_verified = 1
            WHERE id = ?
        ''', (correct_model, record_id))
        conn.commit()
        conn.close()

    def calculate_market_prices(self, brand: str, score: float, has_model: bool) -> dict:
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
            base_val = int(base_val * 1.15)

        condition_factor = max(0.2, score / 100.0)
        
        buy_store_min = int(base_val * condition_factor * 0.52)
        buy_store_max = int(base_val * condition_factor * 0.65)

        fleamarket_min = int(buy_store_min * 1.25)
        fleamarket_max = int(buy_store_max * 1.35)

        auction_min = int(buy_store_min * 1.15)
        auction_max = int(buy_store_max * 1.28)

        return {
            "buy_store": f"{buy_store_min:,}円 ～ {buy_store_max:,}円",
            "fleamarket": f"{fleamarket_min:,}円 ～ {fleamarket_max:,}円",
            "auction": f"{auction_min:,}円 ～ {auction_max:,}円"
        }

growth_ai = GrowthAIEngine()

@app.post("/api/v1/authenticate")
async def authenticate(
    brand: str = Form(...),
    category: str = Form(...),
    model_number: Optional[str] = Form(""),
    serial_number: Optional[str] = Form(""),
    files: List[UploadFile] = File(...)
):
    if not files or len(files) < 1:
        raise HTTPException(status_code=400, detail="画像を1枚以上送信してください。")

    processed_images = []
    total_hash = 0.0
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            img_array = np.array(image.resize((150, 150)), dtype=np.float32) / 255.0
            processed_images.append(img_array)
            total_hash += float(np.mean(img_array) + np.std(img_array))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    feature_hash = round(total_hash / len(processed_images), 4)

    # 過去の正解学習データからの特定
    learned_model = growth_ai.find_learned_model(brand, feature_hash)
    final_model_number = model_number.strip() if model_number.strip() else (learned_model or "")

    total_feature_score = 0.0
    for img in processed_images:
        dx = np.abs(img[1:, :, :] - img[:-1, :, :])
        dy = np.abs(img[:, 1:, :] - img[:, :-1, :])
        edge_density = (np.mean(dx) + np.mean(dy)) * 100.0
        color_std = np.std(img) * 100.0
        score = 82.0 + (edge_density * 0.3) - (color_std * 0.2)
        total_feature_score += score

    avg_score = total_feature_score / len(processed_images)
    if final_model_number:
        avg_score += 5.0

    final_score = round(float(np.clip(avg_score, 35.0, 98.5)), 1)
    market_
