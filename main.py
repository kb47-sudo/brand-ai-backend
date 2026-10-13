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

app = FastAPI(title="Professional AI Authenticator & Valuation Engine", version="39.0")

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
        "engine": "Professional AI Authenticator Engine v39.0",
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
            # 鮮明な刻印照合のため高解像度(1000px)で保持
            image.thumbnail((1000, 1000))
            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=85)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    input_model_info = f"手入力型番/モデル指定: {model_number}" if model_number else "手入力なし（画像解析により完全自動特定）"

    prompt = f"""
あなたは日本の大手大手ブランド買取店（コメ兵・大黒屋・Ginza Rasin等）の最高峰査定部長および真贋鑑識官です。
提出された画像（最大4枚）と以下の条件を元に、プロの鑑識眼で真贋鑑定および3大流通相場（買取・フリマ・オークション）を極めて正確に算出してください。

【査定対象データ】
・ブランド名: {brand}
・カテゴリ: {category}
・{input_model_info}

【絶対遵守の査定・出力ルール】
1. 『detected_model』（自動識別モデル名・型番）:
   - 日本の二次流通市場で用いられる正式な日本語ライン名・モデル名・公式型番・画像から読み取れるシリアル/製造番号を組み合わせて記載してください。
   - 手入力型番（例: M44336, 16233G, H0940等）がある場合はそれを第一優先とし、正式品名（例: 「ルイ・ヴィトン モノグラム・エクリプス ディスカバリー・バムバッグPM (型番: M44336 / 製造番号: BA2260)」）と統合してください。大雑把な英語表記や表記揺れ（バムバンド等）は厳禁です。

2. 『overall_score』（AI一致率スコア）:
   - ロゴ刻印のフォント精度（Rマーク、PARIS文字、文字間隔）、シリアルコードの整合性（例: LVのBA2260ならフランス工場製造＋週/年フォーマット適合性）、ステッチ縫製、金属部品の面取り・メッキ質感・ビス形状を総合評価し、0.0〜100.0の数値で算出。

3. 『judgment』（判定ランク）:
   - 「基準内」「判定保留（要目視査定）」「基準外（偽造品の懸念あり）」の3段階で厳格判定。

4. 『market_prices』（推定市場流通相場）:
   - 日本国内の中古市場（中古良品〜美品コンディション）における実際の取引価格帯を円単位で正確に算出。
   - buy_store: 買取専門店（仕入れ・下取り目安）相場
   - fleamarket: 個人売買（メルカリ・ラクマ等）相場
   - auction: 競り上がり（ヤフオク・ブランドオークション等）相場

5. 『message』（鑑定理由詳細）:
   - なぜそのスコア・判定になったのか、刻印の刻み深さ、シリアルの法則性、金具の質感、素材の目（キャンバス/レザー）に関するプロ目線の解説を日本語で詳しく記述。

【出力JSONフォーマット（JSONコードブロック以外の一切のテキスト出力禁止）】
{{
  "detected_model": "ブランド名 正式ライン・商品名 (型番: XXXXX / シリアル: XXXXX)",
  "overall_score": 95.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "プロ鑑定コメント（刻印、シリアル、金具仕上げ、素材感の具体的なチェック結果）",
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

    # --- 1フェーズ: Gemini API (最高精度メイン) ---
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

    # --- 2フェーズ: OpenRouter API (無料枠フォールバック) ---
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
        return result_data
    except Exception:
        return fallback_response
