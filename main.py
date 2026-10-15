import os
import io
import json
import re
import uuid
import time
import base64
import urllib.request
import urllib.parse
from PIL import Image, ImageEnhance
from fastapi import FastAPI, Form, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import google.generativeai as genai

app = FastAPI(title="Ultra Multi-AI Authenticator & Market Engine", version="124.0")

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
        "engine": "Ultra Multi-AI Authenticator & Market Engine v124.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

def clean_old_jobs():
    now = time.time()
    expired_keys = [k for k, v in JOBS.items() if now - v.get("created_at", now) > 900]
    for k in expired_keys:
        del JOBS[k]

def http_post_json(url: str, headers: dict, data_dict: dict, timeout: int = 25):
    try:
        json_bytes = json.dumps(data_dict).encode('utf-8')
        req = urllib.request.Request(url, data=json_bytes, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                res_body = response.read().decode('utf-8')
                return json.loads(res_body), None
            else:
                return None, f"HTTP Status {response.status}"
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode('utf-8')
            return None, f"HTTP {e.code}: {err_body[:120]}"
        except:
            return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)

def execute_multi_ai_analysis(prompt: str, pil_images: list, base64_images: list):
    logs = []

    # --- 第1優先: Gemini API ---
    if GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            generation_config = {
                "temperature": 0.05,
                "response_mime_type": "application/json"
            }
            for g_model in ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]:
                try:
                    model = genai.GenerativeModel(model_name=g_model, generation_config=generation_config)
                    res = model.generate_content([prompt] + pil_images)
                    if res and hasattr(res, 'text') and res.text:
                        return res.text.strip(), None
                except Exception as g_err:
                    logs.append(f"Gemini({g_model}): {str(g_err)[:80]}")
        except Exception as e:
            logs.append(f"GeminiInit: {str(e)[:80]}")

    # --- 第2優先: OpenRouter API ---
    if OPENROUTER_API_KEY and base64_images:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://brand-ai-backend-1.onrender.com",
            "X-Title": "Brand AI Engine"
        }
        content_payload = [{"type": "text", "text": prompt}]
        for b64_img in base64_images:
            content_payload.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
            })

        for or_model in ["openrouter/free", "google/gemini-2.0-flash-exp:free"]:
            or_payload = {
                "model": or_model,
                "messages": [{"role": "user", "content": content_payload}]
            }
            res_json, err = http_post_json("https://openrouter.ai/api/v1/chat/completions", headers, or_payload, timeout=20)
            if res_json and "choices" in res_json and len(res_json["choices"]) > 0:
                content = res_json["choices"][0]["message"]["content"]
                if content and len(content.strip()) > 0:
                    return content.strip(), None
            logs.append(f"OpenRouter({or_model}): {err or 'Empty'}")

    # --- 第3優先: Groq API ---
    if GROQ_API_KEY and base64_images:
        headers = {
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        }
        content_payload = [{"type": "text", "text": prompt}]
        for b64_img in base64_images:
            content_payload.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{b64_img}"}
            })
        
        for groq_model in ["llama-3.2-11b-vision-preview", "llama-3.3-70b-versatile"]:
            groq_payload = {
                "model": groq_model,
                "messages": [{"role": "user", "content": content_payload}]
            }
            res_json, err = http_post_json("https://api.groq.com/openai/v1/chat/completions", headers, groq_payload, timeout=15)
            if res_json and "choices" in res_json and len(res_json["choices"]) > 0:
                content = res_json["choices"][0]["message"]["content"]
                if content and len(content.strip()) > 0:
                    return content.strip(), None
            logs.append(f"Groq({groq_model}): {err or 'Empty'}")

    return None, f"全AI接続失敗詳細: {' | '.join(logs)}"

def process_authentication_job(job_id: str, brand: str, category: str, model_number: str, base64_images: list, pil_images: list):
    prompt = f"""
あなたは日本のコメ兵、大黒屋、銀座ラシン、銀蔵、コミット銀座等で20年以上の実績を持つ最高峰プロブランド鑑定士および二次流通相場アナリストです。

【入力指定情報】
- ブランド: {brand}
- カテゴリ: {category}
- 条件指定（型番/付属品/コンディション）: {model_number}

【超厳格型番適合性チェック＆動的相場分析プロトコル】
1. 『detected_model』:
   - ユーザーから指定型番の入力がある場合、送信された画像（文字盤、素材、柄、刻印、形状等）が【その型番と100%適合しているか】を照合してください。
   - 適合している場合: 「[型番: 指定型番] ブランド名 ライン名 品名 (型番適合OK)」
   - 型番入力がない場合: 画像から正解の型番を自動特定し「[型番: 自動特定型番] ブランド名 ライン名 品名」
   - 矛盾がある場合: 「[型番不適合アラート] 画像は〇〇ですが型番は××です」の形式で出力すること。

2. 『market_prices』:
   - 指定された「付属品の有無（保証書・箱・コマ等）」および「コンディションランク」を厳密に考慮し、現在の日本国内二次流通相場（日本円）を算出してください。
     - buy_store: 指定条件での買取店仕入れ価格目安（例: "1,850,000円 ～ 2,000,000円"）
     - fleamarket: メルカリ・ラクマ実勢価格
     - auction: ヤフオク・業者オークション落札相場
     - full_set_estimate: もし「ギャランティ・箱など付属品が完備（フルセット）」だった場合の買取上限目安（例: "2,200,000円"）

3. 『message』:
   - 箇条書き（\\n区切り）で以下を出力してください。
     ・型番照合・適合性評価（入力型番と画像の合致度）
     ・付属品による相場変動の解説（保証書有無でいくら変わるか等）
     ・ロゴ刻印・シリアル・仕上げ精度の真贋理由

【出力JSONフォーマット（必ずこのキー構造のJSONのみを出力）】
{{
  "detected_model": "[型番: Ref.126610LN] ロレックス サブマリーナー デイト (型番適合確認)",
  "overall_score": 98.5,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・型番適合確認: 入力されたRef.126610LNと画像の黒文字盤・セラクロムベゼル仕様は100%合致\\n・付属品相場評価: ギャランティカードあり指定のため、本体のみ査定より約15万〜20万円高額評価が適用\\n・刻印解析: ルーレット刻印およびシリアル深さは正規品基準に完全適合\\n・文字盤精度: ROLEXロゴの印刷浮きおよびインデックスの夜光塗料盛りは極めて良好",
  "suspicious_points": [],
  "market_prices": {{
    "buy_store": "1,950,000円 ～ 2,100,000円",
    "fleamarket": "2,200,000円 ～ 2,400,000円",
    "auction": "2,050,000円 ～ 2,200,000円",
    "full_set_estimate": "2,200,000円（付属品完備時の最高買取水準）"
  }},
  "details": [
    {{"name": "1. ブランドロゴフォント・文字配置の正確性", "status": "PASS"}},
    {{"name": "2. シリアル/Ref型番刻印の規則性・深さ", "status": "PASS"}},
    {{"name": "3. 文字盤印刷の精細さと立体感", "status": "PASS"}},
    {{"name": "4. 針の面取り仕上げと夜光塗料塗布精度", "status": "PASS"}},
    {{"name": "5. ベゼル・目盛り刻印のフォントと仕上げ", "status": "PASS"}},
    {{"name": "6. 風防（サファイアガラス）透かし・透過性", "status": "PASS"}},
    {{"name": "7. ケースライン・ラグ部分の仕上げ", "status": "PASS"}},
    {{"name": "8. リューズ刻印と防水パッキン構造", "status": "PASS"}},
    {{"name": "9. バックル/クラスプ刻印の鮮明度", "status": "PASS"}},
    {{"name": "10. 裏蓋刻印・ネジ山の精度", "status": "PASS"}},
    {{"name": "11. ブレスコマの隙間・可動部のガタツキ", "status": "PASS"}},
    {{"name": "12. 全体コンディションと二次流通適合度", "status": "PASS"}}
  ]
}}
"""

    response_text, err_msg = execute_multi_ai_analysis(prompt, pil_images, base64_images)

    if response_text:
        try:
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                clean_json = json_match.group(0)
                result_data = json.loads(clean_json)
                JOBS[job_id] = {"status": "completed", "data": result_data, "created_at": time.time()}
                return
        except Exception as parse_e:
            err_msg = f"JSON解析エラー: {str(parse_e)}"

    JOBS[job_id] = {
        "status": "completed",
        "created_at": time.time(),
        "data": {
            "detected_model": f"{brand} {category} (解析エラー)",
            "overall_score": 0.0,
            "judgment": "エラー発生",
            "status_code": "ERROR",
            "message": f"【解析失敗詳細】:\n{err_msg}",
            "suspicious_points": ["AI応答の取得に失敗しました"],
            "market_prices": {"buy_store": "-- 円", "fleamarket": "-- 円", "auction": "-- 円", "full_set_estimate": "-- 円"},
            "details": []
        }
    }

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

    base64_images = []
    pil_images = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((600, 600))
            image = ImageEnhance.Sharpness(image).enhance(1.2)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=65)
            img_bytes = buffered.getvalue()
            
            pil_images.append(Image.open(io.BytesIO(img_bytes)))
            base64_images.append(base64.b64encode(img_bytes).decode("utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    clean_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "created_at": time.time()}

    background_tasks.add_task(process_authentication_job, job_id, brand, category, model_number, base64_images, pil_images)

    return {"status": "accepted", "job_id": job_id}

@app.get("/api/v1/result/{job_id}")
def get_result(job_id: str):
    clean_old_jobs()
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="指定のジョブが見つかりません。")
    return JOBS[job_id]
