import os
import io
import json
import re
import base64
import requests
from PIL import Image
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from google import genai

app = FastAPI(title="Gemini & Groq Multi-AI Authenticator Engine", version="28.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

@app.get("/")
def read_root():
    return {
        "status": "Live",
        "engine": "Multi-Provider AI Fallback System v28.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

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
    base64_images = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((800, 800))
            pil_images.append(image)

            # Groq API用にBase64エンコード
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG")
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

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

    response_text = None
    last_err = None

    # --- 1フェーズ: Gemini API (メイン) ---
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            res = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=[prompt] + pil_images,
            )
            if res and res.text:
                response_text = res.text.strip()
        except Exception as e:
            last_err = e  # エラー発生時はそのまま下段のGroqへ移行

    # --- 2フェーズ: Groq Vision API (サブ無料枠) ---
    if not response_text and GROQ_API_KEY:
        try:
            headers = {
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            }
            content_payload = [{"type": "text", "text": prompt}]
            for b64_img in base64_images:
                content_payload.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
                })

            groq_payload = {
                "model": "llama-3.2-11b-vision-preview",
                "messages": [{"role": "user", "content": content_payload}],
                "temperature": 0.2
            }
            
            g_res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=groq_payload, timeout=25)
            if g_res.status_code == 200:
                g_json = g_res.json()
                response_text = g_json["choices"][0]["message"]["content"].strip()
            else:
                last_err = f"Groq HTTP {g_res.status_code}: {g_res.text}"
        except Exception as e:
            last_err = e

    if not response_text:
        return {
            "overall_score": 75.0,
            "judgment": "判定保留（無料AI上限到達）",
            "status_code": "REVIEW",
            "detected_model": model_number or "解析一時保留",
            "message": f"すべての無料AIの本日分制限に達しました。時間を置いてお試しください: {str(last_err)}",
            "market_prices": {"buy_store": "算出不能", "fleamarket": "算出不能", "auction": "算出不能"},
            "details": [{"name": "AI解析レスポンス", "pass": False}]
        }

    try:
        clean_json = re.sub(r'```json\s*|\s*```', '', response_text).strip()
        result_data = json.loads(clean_json)
        return result_data
    except Exception as e:
        return {
            "overall_score": 70.0,
            "judgment": "判定保留（データ変換エラー）",
            "status_code": "REVIEW",
            "detected_model": model_number or "解析失敗",
            "message": f"AI応答のパースに失敗しました: {str(e)}",
            "market_prices": {"buy_store": "算出不能", "fleamarket": "算出不能", "auction": "算出不能"},
            "details": [{"name": "データフォーマット適合", "pass": False}]
        }
