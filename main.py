import os
import io
import json
import re
from PIL import Image
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import google.generativeai as genai

app = FastAPI(title="Gemini AI Powered Authenticator Engine", version="16.0")

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
    return {"status": "Live", "engine": "Gemini 1.5 Flash Vision Engine Active"}

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

    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="GEMINI_API_KEY が設定されていません。")

    pil_images = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            pil_images.append(image)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        prompt = f"""
あなたは世界最高峰のブランド真贋鑑定士および中古市場プロ査定士です。
提供された画像（最大4枚）を詳細に解析し、以下の情報を正確なJSON形式のみで出力してください。

対象ブランド: {brand}
指定カテゴリ: {category}
手入力補足型番: {model_number or 'なし'}

【解析命令】
1. 画像の形状、文字盤、刻印、素材感（例: 10Pダイヤ、ジュビリーブレス、コンビ、文字盤色等）から、最も正確な型番・モデル名（例: 16233G デイトジャスト 10Pダイヤ, M61864 ジッピーウォレット 等）を自動特定してください。
2. ブランド真贋の観点から、ロゴフォント・刻印の深さ・金属仕上げ・縫製などを厳格チェックし、真贋一致率スコア（0.0〜100.0）を算出してください。
3. 判定ランクを「基準内」「判定保留（目視確認推奨）」「基準外（偽造品の懸念あり）」のいずれかで決定してください。
4. この特定型番・モデルの現在の「買取店相場」「フリマ相場」「オークション相場」の目安金額を算出してください。

【出力JSON形式（余計な解説文は含めずJSONのみ出力）】
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

        response = model.generate_content([prompt] + pil_images)
        res_text = response.text.strip()
        
        clean_json = re.sub(r'```json\s*|\s*```', '', res_text).strip()
        result_data = json.loads(clean_json)

        return result_data

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Gemini AI解析エラー: {str(e)}")
