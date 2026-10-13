import os
import io
import json
import re
import base64
import requests
from PIL import Image, ImageEnhance
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from google import genai

app = FastAPI(title="Fixed OpenRouter API Engine", version="52.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

@app.get("/")
def read_root():
    return {
        "status": "Live",
        "engine": "Fixed OpenRouter API Engine v52.0",
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "gemini_active": bool(GEMINI_API_KEY)
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
    
    # AI解析用の最適軽量化処理 (600px, quality 80)
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((600, 600))
            
            image = ImageEnhance.Contrast(image).enhance(1.2)
            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=80)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    user_hint = f"ユーザー手入力型番: {model_number}" if model_number else "ユーザー手入力型番: なし（画像から型番を精密自動特定）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋の最高峰鑑定士です。
提出された画像（最大5枚）に【実際に写っている部分だけ】を厳格に鑑識してください。
画像に写っていない部位や判断できない項目について適当に判定（推測で合格にすること）は【絶対に禁止】です。

【査定対象】
・ブランド: {brand}
・カテゴリ: {category}
・{user_hint}

【厳格ルール】
1. 『details』（チェック項目）:
   - 各項目について、画像で確認でき、かつ基準を満たしている場合のみ `"status": "PASS"` (基準内)。
   - 画像で確認でき、不審点・違和感がある場合は `"status": "FAIL"` (不審あり)。
   - 画像に写っていない、または判断がつかない項目は必ず `"status": "UNCHECKED"` (未確認) としてください。

2. 『detected_model』:
   - 画像から判別できる正確な日本語ライン名・公式型番・シリアルを出力。（例: ルイ・ヴィトン モノグラム・エクリプス ディスカバリー・バムバッグPM (型番: M44336 / シリアル: BA2260)）

3. 『message』:
   - 実際に画像で確認できたポイント（刻印、シリアル、金具、素材等）のみを根拠として日本語箇条書きで解説してください。

【出力JSONフォーマット（JSONコードブロックのみ）】
{{
  "detected_model": "ルイ・ヴィトン モノグラム・エクリプス ディスカバリー・バムバッグPM (型番: M44336 / シリアル: BA2260)",
  "overall_score": 98.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・刻印精度: 内部レザータグ刻印のフォントおよび配置が基準適合\\n・シリアル適合度: BA2260（フランス製/2020年第26週）の打刻形式合致\\n・金具仕上げ: ファスナー引き手LV刻印のエッジ・メッキ平滑性良好",
  "suspicious_points": [],
  "market_prices": {{
    "buy_store": "130,000円 ～ 155,000円",
    "fleamarket": "165,000円 ～ 195,000円",
    "auction": "150,000円 ～ 180,000円"
  }},
  "details": [
    {{"name": "1. ロゴフォントの真円性・文字間隔の正確性", "status": "PASS"}},
    {{"name": "2. ®マーク・製造国刻印の凹み形状と底面平坦度", "status": "PASS"}},
    {{"name": "3. シリアル/製造番号の打刻書体・年週法則適合性", "status": "PASS"}},
    {{"name": "4. 金属パーツのエッジ面取り・メッキ層の均一性", "status": "PASS"}},
    {{"name": "5. ビス・ねじ頭のすり割り形状・溝の仕上げ状態", "status": "UNCHECKED"}},
    {{"name": "6. ジッパー・スナップ金具の刻印・噛み合わせ", "status": "PASS"}},
    {{"name": "7. ステッチ（縫い目）の目打ち傾斜角度・ピッチ", "status": "PASS"}},
    {{"name": "8. 素材（レザー/キャンバス）のシボ・柄アライメント", "status": "PASS"}},
    {{"name": "9. コバ処理（バニッシュ塗料の透明度・厚み）", "status": "UNCHECKED"}},
    {{"name": "10. 内側ライニング・裁断面・生地張り質感", "status": "PASS"}},
    {{"name": "11. ギャランティ/シリアルシールのラメ・透かし構造", "status": "UNCHECKED"}},
    {{"name": "12. 全体構造の歪み・自重・各パーツの取付角度", "status": "PASS"}}
  ]
}}
"""

    response_text = None
    last_err = None

    # --- 1フェーズ: OpenRouter API (正しいエンドポイントURL) ---
    if OPENROUTER_API_KEY:
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
                # 正しいAPI URL: https://openrouter.ai/api/v1/chat/completions
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=or_payload, timeout=20)
                if res.status_code == 200:
                    res_json = res.json()
                    if "choices" in res_json and len(res_json["choices"]) > 0:
                        content = res_json["choices"][0]["message"]["content"]
                        if content and len(content.strip()) > 0:
                            response_text = content.strip()
                            break
                last_err = f"OpenRouter status: {res.status_code}"
            except Exception as e:
                last_err = f"OpenRouter Err: {str(e)}"

    # --- 2フェーズ: Gemini API (予備) ---
    if not response_text and GEMINI_API_KEY:
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

    fallback_response = {
        "detected_model": model_number or "解析一時保留（型番自動特定中）",
        "overall_score": 75.0,
        "judgment": "判定保留（一時混雑）",
        "status_code": "REVIEW",
        "message": f"解析が混雑しています。再度査定ボタンを押してください。(Err: {str(last_err)})",
        "suspicious_points": ["解析処理タイムアウトによる確認保留"],
        "market_prices": {"buy_store": "算出不能", "fleamarket": "算出不能", "auction": "算出不能"},
        "details": [
            {"name": "1. ロゴフォントの真円性・文字間隔の正確性", "status": "UNCHECKED"},
            {"name": "2. ®マーク・製造国刻印の凹み形状と底面平坦度", "status": "UNCHECKED"},
            {"name": "3. シリアル/製造番号の打刻書体・年週法則適合性", "status": "UNCHECKED"},
            {"name": "4. 金属パーツのエッジ面取り・メッキ層の均一性", "status": "UNCHECKED"}
        ]
    }

    if not response_text:
        return fallback_response

    try:
        clean_
