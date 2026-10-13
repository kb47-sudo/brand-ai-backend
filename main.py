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

app = FastAPI(title="Authentic Real-Time Precision AI Engine", version="63.0")

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
        "engine": "Authentic Real-Time Precision AI Engine v63.0",
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
    
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((600, 600))
            
            image = ImageEnhance.Sharpness(image).enhance(1.2)
            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=80)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    user_hint = f"ユーザー手入力型番: {model_number}" if model_number else "ユーザー手入力型番: なし（画像から品名・型番を完全自動判別すること）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋等のプロ鑑定士です。
送信された部位写真群（最大5枚）を画像から直接解析し、一切の妥協なくリアルな真贋一致率スコア（0〜100%）と正式な品名・型番、3大市場相場をJSON形式でのみ出力してください。

【対象ブランド】: {brand}
【対象カテゴリ】: {category}
【ヒント】: {user_hint}

【厳格鑑識＆判定ルール】
1. 『detected_model』:
   - 提供された画像（形状、素材、柄、刻印、シリアル）から品物をダイレクトに読み取り、正しい日本語ブランド名・ライン名・商品名・型番を出力してください。

2. 『overall_score』 / 『judgment』:
   - 根拠に基づいたリアルな一致率パーセンテージ（例: 96.5%、88.0%、65.0% 等）を出力してください。適当な90%等の固定数値は厳禁です。
   - 基準内: 95.0%〜100.0%
   - 判定保留: 85.0%〜94.9%
   - 不審あり: 84.9%以下

3. 『suspicious_points』:
   - 画像の刻印フォント、金具の仕上げ、ステッチ、シリアル打刻などを精査し、気になる微小な違和感や不審点があれば具体的に日本語配列で抽出してください。違和感が無ければ `[]` を返してください。

4. 『market_prices』:
   - 判定スコアに関わらず、必ず特定したモデルが本物（正規品）として国内二次流通市場で取引された場合の最新相場（買取店・フリマ・オークションの3つ）を具体的な金額で算出してください。（※「算出中」等の出力は不可）

5. 『details』:
   - 画像で実際に確認できる項目のみ `"status": "PASS"` または `"status": "FAIL"`。写真に写っていない部位は必ず `"status": "UNCHECKED"` とすること。

【出力JSONフォーマット（JSONコードブロックのみ）】
{{
  "detected_model": "画像から特定した正確な日本語ブランド・ライン・品名・型番",
  "overall_score": 96.5,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・刻印精度: 画像から確認できた刻印の精密解説\\n・シリアル適合度: シリアルの解読結果および適合性\\n・金具仕上げ: 金具の仕上げ状態",
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

    # --- 1フェーズ: OpenRouter API (十分な応答時間を確保) ---
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
                # AIが画像5枚を最後まで完全に解析し切るまで35秒しっかり待つ
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=or_payload, timeout=35)
                if res.status_code == 200:
                    res_json = res.json()
                    if "choices" in res_json and len(res_json["choices"]) > 0:
                        content = res_json["choices"][0]["message"]["content"]
                        if content and len(content.strip()) > 0:
                            response_text = content.strip()
                            break
            except Exception:
                continue

    # --- 2フェーズ: Gemini API (バックアップ) ---
    if not response_text and GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            res = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=[prompt] + pil_images,
            )
            if res and res.text:
                response_text = res.text.strip()
        except Exception:
            pass

    if not response_text:
        raise HTTPException(status_code=504, detail="AI解析サーバーが混雑しています。少し時間を置いて再実行してください。")

    try:
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            clean_json = json_match.group(0)
            result_data = json.loads(clean_json)
            return result_data
        else:
            raise HTTPException(status_code=500, detail="解析フォーマットの抽出に失敗しました。")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析データのパースエラー: {str(e)}")
