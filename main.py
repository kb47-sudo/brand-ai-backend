import os
import io
import json
import re
from PIL import Image
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import google.generativeai as genai

app = FastAPI(title="Gemini AI Powered Authenticator Engine", version="17.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)

@app.get("/")
def read_root():
    return {"status": "Live", "engine": "Gemini Vision Active v17.1"}

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

    pil_images = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((800, 800))
            pil_images.append(image)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    if not GEMINI_API_KEY:
        return {
            "overall_score": 85.0,
            "judgment": "判定保留（APIキー未設定）",
            "status_code": "REVIEW",
            "detected_model": model_number or "16233G (デイトジャスト)",
            "message": "RenderのEnvironmentに GEMINI_API_KEY が正しく設定されていません。",
            "market_prices": {"buy_store": "750,000円 ～ 900,000円", "fleamarket": "900,000円 ～ 1,200,000円", "auction": "850,000円 ～ 1,100,000円"},
            "details": [{"name": "API接続確認", "pass": False}]
        }

    # 利用可能な安定モデルを順に試行するロジック
    candidate_models = ['gemini-2.5-flash', 'gemini-1.5-flash-latest', 'gemini-1.5-pro']
    response_text = None
    last_error = None

    prompt = f"""
あなたは最高峰の高級ブランド鑑定士および中古市場プロ査定士です。
提供された画像（最大4枚）を解析し、正確なJSON形式のみで出力してください。

対象ブランド: {brand}
カテゴリ: {category}
手入力補足: {model_number or 'なし'}

【解析命令】
1. 画像（文字盤、ダイヤ、ブレス、刻印、フレーム形状等）から最も正確な型番・モデル名（例: 16233G デイトジャスト 10Pダイヤ, Z2434U, M61864 等）を自動識別してください。
2. 真贋一致率スコア（0.0〜100.0）を算出してください。
3. 判定ランク（「基準内」「判定保留（目視確認推奨）」「基準外（偽造品の懸念あり）」）を決定してください。
4. 推定「買取店相場」「フリマ相場」「オークション相場」の金額（円）を算出してください。

【出力JSON形式（JSON以外の文字は一切禁止）】
{{
  "detected_model": "特定された型番・品名",
  "overall_score": 88.5,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "鑑定コメント詳細",
  "market_prices": {{
    "buy_store": "◯◯円 ～ ◯◯円",
    "fleamarket": "◯◯円 ～ ◯◯円",
    "auction": "◯◯円 ～ ◯◯円"
  }},
  "details": [
    {{"name": "ロゴフォント・刻印配置の正確性", "pass": true}},
    {{"name": "素材仕上げ・研磨・バリ処理の質感", "pass": true}},
    {{"name": "シリアル/製造番号のフォーマット適合", "pass": true}},
    {{"name": "細部構造・金具部品の基準一致", "pass": true}}
  ]
}}
"""

    for m_name in candidate_models:
        try:
            model = genai.GenerativeModel(m_name)
            res = model.generate_content([prompt] + pil_images)
            if res and res.text:
                response_text = res.text.strip()
                break
        except Exception as err:
            last_error = err
            continue

    if not response_text:
        return {
            "overall_score": 75.0,
            "judgment": "判定保留（AI通信エラー）",
            "status_code": "REVIEW",
            "detected_model": model_number or "解析失敗",
            "message": f"Gemini API通信エラー: {str(last_error)}",
            "market_prices": {"buy_store": "算出不能", "fleamarket": "算出不能
