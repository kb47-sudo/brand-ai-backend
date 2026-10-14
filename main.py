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

app = FastAPI(title="Multi-AI Fallback Engine", version="121.0")

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
        "engine": "Multi-AI Fallback Engine v121.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

def clean_old_jobs():
    now = time.time()
    expired_keys = [k for k, v in JOBS.items() if now - v.get("created_at", now) > 600]
    for k in expired_keys:
        del JOBS[k]

def http_post_json(url: str, headers: dict, data_dict: dict, timeout: int = 20):
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

    # --- フェーズ 1: Gemini (Google SDK経由) ---
    if GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            generation_config = {
                "temperature": 0.05,
                "response_mime_type": "application/json"
            }
            for g_model in ["gemini-2.0-flash", "gemini-1.5-flash"]:
                try:
                    model = genai.GenerativeModel(model_name=g_model, generation_config=generation_config)
                    res = model.generate_content([prompt] + pil_images)
                    if res and hasattr(res, 'text') and res.text:
                        return res.text.strip(), None
                except Exception as g_err:
                    logs.append(f"Gemini({g_model}): {str(g_err)[:80]}")
        except Exception as e:
            logs.append(f"GeminiInit: {str(e)[:80]}")

    # --- フェーズ 2: OpenRouter API ---
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

        for or_model in ["openrouter/free", "google/gemma-4-26b-a4b-it:free"]:
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

    # --- フェーズ 3: Groq API ---
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
        
        for groq_model in ["qwen-2.5-32b", "llama-3.3-70b-versatile"]:
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
    user_hint = f"ユーザー手入力補足: {model_number}" if model_number else "ユーザー手入力補足: なし（画像から正確な型番・ライン名・品名を特定すること）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋・銀座ラシン・銀蔵で20年以上の実績を持つ最高峰のブランド鑑定士です。
提供された部位画像群（全体、刻印、シリアル・製造番号、金具、内装等）を精密に視覚解析し、該当する製品の【正確な型番（モデルナンバー）】および【本物一致率】と【最新市場相場】を判定してください。

【指定ブランド】: {brand}
【指定カテゴリ】: {category}
【ヒント情報】: {user_hint}

【型番特定＆高精度鑑識ルール】
1. 『detected_model』:
   - 画像に写っている製品のライン（モノグラム・エクリプス、ダミエ、グラフィット等）、形状（ディスカバリー・バムバッグ、アヴェニュー・スリングバッグ等）、およびシリアル刻印の製造年（例: BA2260→2020年26週フランス製）を多角照合し、ルイ・ヴィトンの正式型番（例: M44388, N41719 等）を特定してください。
   - 必ず「[型番: 型番コード] ブランド名 ライン名 正式品名」のフォーマットで出力すること。

2. 『message』:
   - 英文や奇妙な単語（"キャンバス_used_" や "MESSキ" など）を一切排除し、完全に自然でプロフェッショナルな日本語の箇条書き（\\n区切り）で鑑識理由を記載すること。
   - シリアル記号の製造工場と年週の解説、刻印フォントの評価、金具メッキの質感評価を含めること。

3. 『market_prices』:
   - 特定された型番・モデルに基づき、日本国内の二次流通市場の実勢相場（日本円）を算出すること。

【出力JSONフォーマット（必ずこのキー構造のJSONのみを出力）】
{{
  "detected_model": "[型番: M44388] ルイ・ヴィトン モノグラム・エクリプス ディスカバリー・バムバッグ",
  "overall_score": 97.5,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・型番特定: モノグラム・エクリプスキャンバスとフロントポケット形状、シリアルよりM44388と特定\\n・刻印解析: 内部レザーパッチの「LOUIS VUITTON PARIS made in France」刻印フォントおよび文字配置は正規品基準に適合\\n・シリアル解析: 「BA2260」はフランス工場にて2020年第26週に製造された規則性に完全合致\\n・金具品質: ジッパータブおよびバックル金具の刻印深さとメッキの質感は極めて良好",
  "suspicious_points": [],
  "market_prices": {{
    "buy_store": "110,000円 ～ 130,000円",
    "fleamarket": "140,000円 ～ 160,000円",
    "auction": "125,000円 ～ 145,000円"
  }},
  "details": [
    {{"name": "1. ロゴフォントの真円性・文字間隔の正確性", "status": "PASS"}},
    {{"name": "2. シリアル/製造番号の規則性・フォント合致", "status": "PASS"}},
    {{"name": "3. レザーパッチの縫製（ステッチ数と糸の質）", "status": "PASS"}},
    {{"name": "4. モノグラムキャンバスの印刷鮮明度と配置", "status": "PASS"}},
    {{"name": "5. キャンバス生地の質感と張り", "status": "PASS"}},
    {{"name": "6. 金具（ジッパー・バックル）のメッキ均一性", "status": "PASS"}},
    {{"name": "7. 金具ロゴ（LVマーク）の刻印深さとエッジ処理", "status": "PASS"}},
    {{"name": "8. 縫製の均一性と糸の質（本縫い）", "status": "PASS"}},
    {{"name": "9. 製造国表記（made in France）の整合性", "status": "PASS"}},
    {{"name": "10. バックルの作動と構造", "status": "PASS"}},
    {{"name": "11. シェイプの対称性とカーブの美しさ", "status": "PASS"}},
    {{"name": "12. 内部構成とポケット設計", "status": "PASS"}}
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
            "market_prices": {"buy_store": "-- 円", "fleamarket": "-- 円", "auction": "-- 円"},
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
            image.thumbnail((800, 800))
            image = ImageEnhance.Sharpness(image).enhance(1.2)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=80)
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
