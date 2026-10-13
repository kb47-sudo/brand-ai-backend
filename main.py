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

app = FastAPI(title="Professional AI Authenticator & Valuation Engine", version="40.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

@app.get("/")
def read_root():
    return {
        "status": "Live",
        "engine": "Professional AI Authenticator Engine v40.0",
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
            image.thumbnail((1000, 1000))
            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=85)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    input_model_info = f"手入力指定型番: {model_number}" if model_number else "手入力なし（画像解析により自動特定）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋等のプロ鑑定士です。
提出された画像と情報から、正確な真贋判定および最新の中古市場流通相場を厳密に算出し、JSON形式でのみ出力してください。

【査定対象データ】
・ブランド: {brand}
・カテゴリ: {category}
・{input_model_info}

【最重要ルール】
1. 『detected_model』:
   - 正確な日本語商品名＋公式型番＋画像から解読できる製造番号（シリアル）を出力してください。
   - 「バムバンド」などの造語・誤記は絶対に禁止です。「バムバッグ」と正確に記載してください。
   - M44336 の場合の正解表記例: 「ルイ・ヴィトン モノグラム・エクリプス ディスカバリー・バムバッグPM (型番: M44336 / シリアル: BA2260)」

2. 『market_prices』:
   - 日本のブランド中古市場における現実的な買取店（仕入れ）・フリマ・オークションの実勢価格帯（円）を算出してください。
   - 例: M44336（ディスカバリー・バムバッグPM）の場合、買取店10万円〜13万円、フリマ13.5万円〜16.5万円、オークション12万円〜15万円 のように現在の国内実勢市場価格を正確に提示してください。

3. 『overall_score』 / 『judgment』 / 『message』:
   - ロゴ刻印（PARISフォント・Rマーク・間隔）、シリアル（BA2260等＝フランス工場製＋製造年週法則）、金具仕上げ（エッジ・メッキ厚）、キャンバスの目から0.0〜100.0のスコアと詳細評価を作成してください。

【出力JSONフォーマット（JSONコードブロックのみ）】
{{
  "detected_model": "ルイ・ヴィトン モノグラム・エクリプス ディスカバリー・バムバッグPM (型番: M44336 / シリアル: BA2260)",
  "overall_score": 95.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "鑑定コメント詳細",
  "market_prices": {{
    "buy_store": "100,000円 ～ 130,000円",
    "fleamarket": "135,000円 ～ 165,000円",
    "auction": "120,000円 ～ 150,000円"
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

    # --- 2フェーズ: OpenRouter API (フォールバック) ---
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
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=or_payload, timeout=25)
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
        
        # 強制補正（「バムバンド」誤記をプログラム側で「バムバッグ」へ最終強制変換）
        if "detected_model" in result_data and isinstance(result_data["detected_model"], str):
            result_data["detected_model"] = result_data["detected_model"].replace("バムバンド", "バムバッグ")
        if "message" in result_data and isinstance(result_data["message"], str):
            result_data["message"] = result_data["message"].replace("バムバンド", "バムバッグ")

        return result_data
    except Exception:
        return fallback_response
