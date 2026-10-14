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

app = FastAPI(title="Multi-AI Fallback Engine", version="120.0")

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
        "engine": "Multi-AI Fallback Engine v120.0",
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
                "temperature": 0.1,
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

    # --- フェーズ 2: OpenRouter API (自動ビジョンルーター & 無料モデル) ---
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

    # --- フェーズ 3: Groq API (Qwen / Llama Vision) ---
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
    user_hint = f"ユーザー手入力補足: {model_number}" if model_number else "ユーザー手入力補足: なし（画像から型番・正式名称・ライン名を完全自動判別すること）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋・銀座ラシン等の最高峰ブランド鑑定士および買取市場相場アナリストです。
送信された複数枚の部位画像（外観、刻印、シリアル・製造番号、金具、内側等）を精密解析し、品物を厳格に特定してください。

【指定ブランド】: {brand}
【指定カテゴリ】: {category}
【ヒント情報】: {user_hint}

【超厳格判定ルール＆型番完全特定プロトコル】
1. 『detected_model』:
   - 画像に写っているモノグラム/ダミエ/エピ等のライン名、形状、シリアル刻印パターンから【正式型番（例: M44336, M60017, N41661 等）】を特定し、必ず「[型番: 型番コード] ブランド名 ライン名 正式品名」の形式で出力してください。型番が判定不可能な場合は「[型番: 不明] ブランド名 品名」としてください。

2. 『market_prices』:
   - 特定された型番および品物に基づき、日本国内の最新二次流通相場（日本円）を算出してください。
     - buy_store: 買取店仕入れ相場（例: "50,000円 ～ 65,000円"）
     - fleamarket: メルカリ・ラクマ販売相場（例: "68,000円 ～ 78,000円"）
     - auction: ヤフオク落札相場（例: "58,000円 ～ 70,000円"）

3. 『overall_score』 / 『judgment』:
   - 画像内の刻印フォント、縫製、金具メッキ、素材感等から算出した本物一致率スコア（0.0〜100.0%）と判定ランク（"基準内" / "注意" / "基準外"）を出力してください。

4. 『message』:
   - 画像解析から得られたプロ鑑定士としての総評・レポート根拠を日本語の箇条書き（\\n区切り）で詳細に記載してください。

5. 『suspicious_points』:
   - 画像で検知された違和感（刻印の歪み、フォント不適合、シリアル法則の不一致等）があれば配列で抽出。無ければ [] とすること。

6. 『details』:
   - 12個の多角チェック項目（ロゴ刻印、シリアル、金具、縫製等）に対し、画像で確認できた項目は "PASS" または "FAIL"、未確認画像は "UNCHECKED" とすること。

【出力JSONフォーマット（必ずこの形式のJSONのみを出力）】
{{
  "detected_model": "[型番: M44336] ルイ・ヴィトン モノグラム ジッピー・ウォレット",
  "overall_score": 96.5,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・型番特定: モノグラムライン・最新カードポケット構成よりM44336と特定\\n・刻印解析: France表記フォントおよび文字配置精度は基準内\\n・シリアル適合度: 製造年週と工場コードの整合性を確認",
  "suspicious_points": [],
  "market_prices": {{
    "buy_store": "55,000円 ～ 65,000円",
    "fleamarket": "70,000円 ～ 82,000円",
    "auction": "60,000円 ～ 72,000円"
  }},
  "details": [
    {{"name": "1. ロゴフォントの真円性・文字間隔の正確性", "status": "PASS"}},
    {{"name": "2. シリアル/製造番号の規則性・フォント合致", "status": "PASS"}}
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
