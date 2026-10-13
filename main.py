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

app = FastAPI(title="Dynamic High-Speed AI Authenticator Engine", version="41.0")

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
        "engine": "Dynamic High-Speed AI Authenticator Engine v41.0",
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
    
    # 高速化・通信タイムアウト防止のための超軽量画像処理 (500px, JPEG品質70)
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((500, 500))
            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=70)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    user_hint = f"ユーザー提示型番: {model_number}" if model_number else "ユーザー提示型番: なし（画像から完全自動解析して判定）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋等で10万点以上を査定してきたトップブランド鑑定士です。
送信された画像群を先入観なくゼロベースで厳密解析し、正確なJSON形式のみで出力してください。

【対象ブランド】: {brand}
【対象カテゴリ】: {category}
【ヒント情報】: {user_hint}

【絶対精度命令】
1. 『detected_model』:
   - 画像の形状、柄（モノグラム/ダミエ/エピ等）、構造、縦ライン、ストラップ等から正確な製品名と型番を識別してください。
   - 例: ダミエ・エベヌのセカンドバッグで縦レザーバンドがある場合は「ルイ・ヴィトン ダミエ・エベヌ サンルイ (型番: N51993)」のようにピンポイント特定してください。過去の無関係な型番を出力することは厳禁です。

2. 『market_prices』:
   - 特定した製品（例: サンルイ N51993）の日本国内の中古流通市場（美品〜並品コンディション）の最新実勢相場を正確に算出してください。
   - 他の高級バッグの相場に引っ張られず、その製品自体の正確な相場帯（買取店・フリマ・オークション）を円単位で出力してください。

3. 『overall_score』 / 『judgment』 / 『message』:
   - 柄のアライメント、刻印文字、金具処理、シリアルフォーマット等を多角的検証し、真贋スコア（0〜100）と理由を出力してください。

【出力JSON構造（他の余分な文章・注釈は一切禁止）】
{{
  "detected_model": "正確なブランド・ライン・製品名 (型番: XXXX / シリアル: XXXX)",
  "overall_score": 92.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "刻印、生地の目、金具、シリアルフォーマットに基づく鑑定解説",
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
            last_err = f"Gemini Limit: {str(e)}"

    # --- 2フェーズ: OpenRouter API (高速フォールバック) ---
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
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=or_payload, timeout=15)
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
