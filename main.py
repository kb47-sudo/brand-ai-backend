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

app = FastAPI(title="5-Slot Multi-Vision AI Authenticator Engine", version="43.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

@app.get("/")
def read_root():
    return {
        "status": "Live",
        "engine": "5-Slot Multi-Vision AI Authenticator Engine v43.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
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
            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=75)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    user_hint = f"ユーザー指定補足型番: {model_number}" if model_number else "ユーザー指定補足型番: なし（画像解析により完全自動特定）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋等のプロ鑑定士です。
送信された画像群（最大5枚：表面、裏面、刻印、シリアル、金具）を多角的に照合し、正確な製品名・公式型番・製造番号（シリアル）・市場相場を特定してJSON形式でのみ出力してください。

【対象ブランド】: {brand}
【対象カテゴリ】: {category}
【ヒント】: {user_hint}

【絶対査定ルール】
1. 『detected_model』:
   - 表面デザインだけでなく、**裏面（背面ポケット、ベルトストラップ形状、マチ構造）**の画像を精査し、類似モデルと誤認せずに正確な商品名と型番を決定してください。
   - ユーザー指定型番がある場合はそれを最優先し、正確な日本語ライン名と統合してください。
   - 例: 「ルイ・ヴィトン モノグラム・エクリプス ディスカバリー・バムバッグPM (型番: M44336 / シリアル: BA2260)」

2. 『market_prices』:
   - 特定された製品の日本国内中古市場（美品〜並品）におけるリアルな実勢取引価格を算出して出力。
   - 買取店相場（仕入れ）、フリマ相場（メルカリ等）、オークション相場（ヤフオク等）をそれぞれ提示。

3. 『overall_score』 / 『judgment』 / 『message』:
   - ロゴ刻印（文字間隔・Rマーク）、シリアルコードの整合性、裏面構造、金具仕上げから総合判定（0.0〜100.0）とプロ目線の解説を作成。

【出力JSONフォーマット（JSONコードブロックのみ）】
{{
  "detected_model": "ブランド名 ライン・製品名 (型番: XXXX / シリアル: XXXX)",
  "overall_score": 95.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "表面・裏面構造、刻印、シリアルフォーマットに基づく詳細鑑定解説",
  "market_prices": {{
    "buy_store": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円",
    "fleamarket": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円",
    "auction": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円"
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

    # --- 1フェーズ: Gemini API ---
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
            last_err = f"Gemini Limit: {str(e)}"

    # --- 2フェーズ: OpenRouter API ---
    if not response_text and OPENROUTER_API_KEY:
        openrouter_models = [
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.2-11b-vision-instruct:free",
            "openrouter/free"
        ]
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        content_payload = [{"type": "text", "text": prompt}]
        for b64_img in base64_images:
            content_payload.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
            })

        for or_model in openrouter_models:
            try:
                or_payload = {
                    "model": or_model,
                    "messages": [{"role": "user", "content": content_payload}]
                }
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=or_payload, timeout=20)
                if res.status_code == 200:
                    res_json = res.json()
                    if "choices" in res_json and len(res_json["choices"]) > 0:
                        content = res_json["choices"][0]["message"]["content"]
                        if content and len(content.strip()) > 0:
                            response_text = content.strip()
                            break
                last_err = f"OpenRouter ({or_model}: {res.status_code})"
            except Exception as e:
                last_err = f"OpenRouter Err: {str(e)}"

    fallback_response = {
        "detected_model": model_number or "解析一時保留（型番自動特定中）",
        "overall_score": 75.0,
        "judgment": "判定保留（一時混雑）",
        "status_code": "REVIEW",
        "message": f"解析が一時的に混雑しています。再度査定ボタンを押してください: {str(last_err)}",
        "market_prices": {"buy_store": "算出不能", "fleamarket": "算出不能", "auction": "算出不能"},
        "details": [
            {"name": "ロゴフォント・刻印配置の正確性", "pass": False},
            {"name": "素材仕上げ・研磨・バリ処理の質感", "pass": False},
            {"name": "シリアル/製造番号のフォーマット適合", "pass": False},
            {"name": "細部構造・金具部品の基準一致", "pass": False}
        ]
    }

    if not response_text:
        return fallback_response

    try:
        clean_json = re.sub(r'```json\s*|\s*```', '', response_text).strip()
        result_data = json.loads(clean_json)
        return result_data
    except Exception:
        return fallback_response
