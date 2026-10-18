import os
import io
import json
import re
import uuid
import time
import base64
import urllib.request
from PIL import Image, ImageEnhance
from fastapi import FastAPI, Form, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional

app = FastAPI(title="Pro Authenticator Engine", version="146.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

JOBS = {}

@app.get("/")
def read_root():
    return {
        "status": "Live",
        "engine": "Pro Authenticator Engine v146.0",
        "gemini_active": bool(GEMINI_API_KEY)
    }

def clean_old_jobs():
    now = time.time()
    for k in list(JOBS.keys()):
        if now - JOBS[k].get("created_at", now) > 900:
            JOBS.pop(k, None)

def get_gemini_models():
    if not GEMINI_API_KEY:
        return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                models = []
                for m in data.get("models", []):
                    if "generateContent" in m.get("supportedGenerationMethods", []):
                        models.append(m.get("name", "").replace("models/", ""))
                return models
    except Exception:
        pass
    return ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]

def call_gemini(model_name: str, prompt: str, base64_images: list):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
    headers = {"Content-Type": "application/json"}

    parts = [{"text": prompt}]
    for b64 in base64_images:
        parts.append({"inline_data": {"mime_type": "image/jpeg", "data": b64}})

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
    }

    try:
        json_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=json_bytes, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=30) as response:
            if response.status == 200:
                res_json = json.loads(response.read().decode('utf-8'))
                if "candidates" in res_json and len(res_json["candidates"]) > 0:
                    cand = res_json["candidates"][0]
                    if "content" in cand and "parts" in cand["content"] and len(cand["content"]["parts"]) > 0:
                        return cand["content"]["parts"][0].get("text", "").strip(), None
            return None, f"Status {response.status}"
    except urllib.error.HTTPError as e:
        try:
            return None, f"HTTP {e.code}: {e.read().decode('utf-8')[:100]}"
        except Exception:
            return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)

def execute_gemini_analysis(prompt: str, base64_images: list):
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEYが未設定です。"

    models = get_gemini_models()
    if not models:
        models = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]

    logs = []
    for m in models:
        res_text, err = call_gemini(m, prompt, base64_images)
        if res_text:
            return res_text, None
        logs.append(f"{m}: {err}")

    return None, f"Gemini通信エラー: {' | '.join(logs[:3])}"

@app.post("/api/v1/detect_candidates")
async def detect_candidates(
    background_tasks: BackgroundTasks,
    brand: str = Form(...),
    category: str = Form(...),
    files: List[UploadFile] = File(...)
):
    if not files:
        raise HTTPException(status_code=400, detail="画像なし")

    base64_images = []
    for file in files:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents)).convert('RGB')
        image.thumbnail((600, 600))
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG", quality=65)
        base64_images.append(base64.b64encode(buffered.getvalue()).decode("utf-8"))

    clean_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "created_at": time.time()}

    prompt = f"ブランド:{brand}\nカテゴリ:{category}\n型番候補3つをJSONで返してください。\nフォーマット: {{\"candidates\":[{{\"id\":1,\"title\":\"[型番: M44336] ルイ・ヴィトン ネオノエ MM\",\"desc\":\"モノグラム\"}},{{\"id\":2,\"title\":\"[型番: M40995] ルイ・ヴィトン ネヴァーフル MM\",\"desc\":\"モノグラム\"}},{{\"id\":3,\"title\":\"[型番: M45254] ルイ・ヴィトン リポーター PM\",\"desc\":\"モノグラム\"}}]}}"

    def bg_task():
        res, err = execute_gemini_analysis(prompt, base64_images)
        if res:
            try:
                cleaned = re.sub(r'```json\s*', '', re.sub(r'```\s*$', '', res)).strip()
                match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if match:
                    JOBS[job_id] = {"status": "completed", "data": json.loads(match.group(0)), "created_at": time.time()}
                    return
            except Exception:
                pass
        JOBS[job_id] = {
            "status": "completed",
            "created_at": time.time(),
            "data": {"candidates": [
                {"id": 1, "title": f"{brand} {category} (標準照合)", "desc": "主要モデル"},
                {"id": 2, "title": f"{brand} {category} (類似モデル)", "desc": "類似モデル"},
                {"id": 3, "title": f"{brand} {category} (手入力)", "desc": "手入力"}
            ]}
        }

    background_tasks.add_task(bg_task)
    return {"status": "accepted", "job_id": job_id}

@app.post("/api/v1/authenticate")
async def authenticate(
    background_tasks: BackgroundTasks,
    brand: str = Form(...),
    category: str = Form(...),
    model_number: Optional[str] = Form(""),
    files: List[UploadFile] = File(...)
):
    if not files:
        raise HTTPException(status_code=400, detail="画像なし")

    base64_images = []
    for file in files:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents)).convert('RGB')
        image.thumbnail((600, 600))
        buffered = io.BytesIO()
        image.save(buffered, format="JPEG", quality=65)
        base64_images.append(base64.b64encode(buffered.getvalue()).decode("utf-8"))

    clean_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "created_at": time.time()}

    prompt = f"ブランド:{brand}\nカテゴリ:{category}\n型番:{model_number}\n鑑識・定価・相場をJSONで返してください。\nフォーマット: {{\"detected_model\":\"ルイ・ヴィトン ネオノエ MM (M44336)\",\"official_price\":\"272,800円\",\"overall_score\":96.0,\"judgment\":\"基準内\",\"status_code\":\"PASS\",\"message\":\"適合確認\",\"suspicious_points\":[],\"market_prices\":{{\"buy_store\":\"130,000円 ～ 150,000円\",\"fleamarket\":\"160,000円 ～ 180,000円\",\"auction\":\"145,000円 ～ 165,000円\",\"full_set_estimate\":\"160,000円\"}},\"details\":[{{\"name\":\"1.ロゴ\",\"status\":\"PASS\"}}]}}"

    def bg_task():
        res, err = execute_gemini_analysis(prompt, base64_images)
        if res:
            try:
                cleaned = re.sub(r'```json\s*', '', re.sub(r'```\s*$', '', res)).strip()
                match = re.search(r'\{.*\}', cleaned, re.DOTALL)
                if match:
                    JOBS[job_id] = {"status": "completed", "data": json.loads(match.group(0)), "created_at": time.time()}
                    return
            except Exception:
                pass
        JOBS[job_id] = {
            "status": "completed",
            "created_at": time.time(),
            "data": {
                "detected_model": f"{brand} {category} (解析エラー)",
                "official_price": "-- 円",
                "overall_score": 0.0,
                "judgment": "エラー発生",
                "status_code": "ERROR",
                "message": f"【解析失敗】: {err}",
                "suspicious_points": ["AI取得失敗"],
                "market_prices": {"buy_store": "-- 円", "fleamarket": "-- 円", "auction": "-- 円", "full_set_estimate": "-- 円"},
                "details": []
            }
        }

    background_tasks.add_task(bg_task)
    return {"status": "accepted", "job_id": job_id}

@app.get("/api/v1/result/{job_id}")
def get_result(job_id: str):
    clean_old_jobs()
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="ジョブなし")
    return JOBS[job_id]
