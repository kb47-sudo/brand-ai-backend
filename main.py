import os
import io
import json
import re
import uuid
import base64
import requests
from PIL import Image, ImageEnhance
from fastapi import FastAPI, Form, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from google import genai

app = FastAPI(title="Dynamic Market Valuation AI Authenticator Engine", version="69.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

JOBS = {}

@app.get("/")
def read_root():
    return {
        "status": "Live",
        "engine": "Dynamic Market Valuation AI Authenticator v69.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

def process_authentication_job(job_id: str, brand: str, category: str, model_number: str, base64_images: list, pil_images: list):
    user_hint = f"ユーザー手入力型番: {model_number}" if model_number else "ユーザー手入力型番: なし（画像から品名・型番を完全自動判別すること）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋・銀座ラシン等のプロ鑑定士および買取相場アナリストです。
送信された部位写真群（最大5枚）を画像から直接解析し、品物を特定した上で、リアルな真贋一致率スコア（0〜100%）と、その特定された品物の【日本国内における最新のリアルな実勢相場】を個別に算出してJSON形式でのみ出力してください。

【対象ブランド】: {brand}
【対象カテゴリ】: {category}
【ヒント】: {user_hint}

【厳格鑑識＆動的相場算出ルール】
1. 『detected_model』:
   - 提供された画像（形状、素材、柄、刻印、シリアル）から品物をダイレクトに読み取り、正しい日本語ブランド名・ライン名・商品名・型番を出力してください。

2. 『market_prices』 (最重要・動的算出):
   - 特定した『detected_model』（品名・型番）に基づき、日本国内の二次流通市場での適正相場をそれぞれ個別に算出して具体的に出力してください。
   - テンプレや他商品の数値を使い回すことは【絶対に禁止】です。必ず画像から特定された商品（例: 時計ならRef番号、バッグならラインや型番）に応じた実勢価格を試算してください。
     - buy_store: 買取店仕入れ目安（例: "◯◯◯,◯◯◯円 ～ ◯◯◯,◯◯◯円"）
     - fleamarket: メルカリ・ラクマ等の販売相場
     - auction: ヤフオク等の落札相場

3. 『overall_score』 / 『judgment』:
   - 根拠に基づいたリアルな一致率パーセンテージを出力してください。固定値の使い回しは禁止です。
   - 基準内: 95.0%〜100.0%
   - 判定保留: 85.0%〜94.9%
   - 不審あり: 84.9%以下

4. 『suspicious_points』:
   - 画像の刻印フォント、金具の仕上げ、ステッチ、シリアル打刻などを精査し、気になる微小な違和感や不審点があれば具体的に日本語配列で抽出してください。違和感が無ければ `[]` を返してください。

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
    "buy_store": "特定モデルに応じたリアル買取相場",
    "fleamarket": "特定モデルに応じたリアルフリマ相場",
    "auction": "特定モデルに応じたリアルオークション相場"
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

    # --- 第1フェーズ: Google Gemini API (本命モデル) ---
    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            res = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt] + pil_images,
            )
            if res and res.text:
                response_text = res.text.strip()
        except Exception:
            pass

    # --- 第2フェーズ: OpenRouter API ---
    if not response_text and OPENROUTER_API_KEY:
        openrouter_models = [
            "meta-llama/llama-3.2-11b-vision-instruct:free",
            "qwen/qwen-2-vl-72b-instruct:free",
            "google/gemini-2.0-flash-exp:free"
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
            except Exception:
                continue

    # --- 第3フェーズ: Groq API ---
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
            res = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=groq_payload, timeout=15)
            if res.status_code == 200:
                res_json = res.json()
                if "choices" in res_json and len(res_json["choices"]) > 0:
                    content = res_json["choices"][0]["message"]["content"]
                    if content and len(content.strip()) > 0:
                        response_text = content.strip()
        except Exception:
            pass

    if response_text:
        try:
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                clean_json = json_match.group(0)
                result_data = json.loads(clean_json)
                JOBS[job_id] = {"status": "completed", "data": result_data}
                return
        except Exception as e:
            JOBS[job_id] = {"status": "error", "message": f"パースエラー: {str(e)}"}
            return

    JOBS[job_id] = {"status": "error", "message": "API制限および全モデル混雑のため解析を完了できませんでした。少し時間を置いてお試しください。"}

@app.post("/api/v1/authenticate")
async def authenticate(
    background_tasks: BackgroundTasks,
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
            image.thumbnail((550, 550))
            
            image = ImageEnhance.Sharpness(image).enhance(1.2)
            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=75)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing"}

    background_tasks.add_task(process_authentication_job, job_id, brand, category, model_number, base64_images, pil_images)

    return {"status": "accepted", "job_id": job_id}

@app.get("/api/v1/result/{job_id}")
def get_result(job_id: str):
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="指定のジョブが見つかりません。")
    return JOBS[job_id]
