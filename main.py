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

app = FastAPI(title="Pro Authenticator Engine", version="145.0")

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
        "engine": "Pro Authenticator Engine v145.0 (Auto-Resolver)",
        "gemini_active": bool(GEMINI_API_KEY)
    }

def clean_old_jobs():
    now = time.time()
    for k in list(JOBS.keys()):
        if now - JOBS[k].get("created_at", now) > 900:
            JOBS.pop(k, None)

def get_available_gemini_models(api_key: str):
    """Google APIから現在利用可能なモデル一覧を直接取得"""
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        req = urllib.request.Request(url, method='GET')
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                models = []
                for m in data.get("models", []):
                    methods = m.get("supportedGenerationMethods", [])
                    if "generateContent" in methods:
                        # "models/gemini-1.5-flash" -> "gemini-1.5-flash"
                        name = m.get("name", "").replace("models/", "")
                        models.append(name)
                # flash系を優先
                flash_models = [m for m in models if "flash" in m]
                other_models = [m for m in models if "flash" not in m]
                return flash_models + other_models
    except Exception as e:
        pass
    # フォールバック用デフォルトリスト
    return ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]

def call_gemini_direct(api_key: str, model_name: str, prompt: str, base64_images: list):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}

    parts = [{"text": prompt}]
    for b64 in base64_images:
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": b64
            }
        })

    payload = {
        "contents": [{"parts": parts}],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json"
        }
    }

    try:
        json_bytes = json.dumps(payload).encode('utf-8')
        req = urllib.request.Request(url, data=json_bytes, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=35) as response:
            if response.status == 200:
                res_body = response.read().decode('utf-8')
                res_json = json.loads(res_body)
                if "candidates" in res_json and len(res_json["candidates"]) > 0:
                    cand = res_json["candidates"][0]
                    if "content" in cand and "parts" in cand["content"] and len(cand["content"]["parts"]) > 0:
                        return cand["content"]["parts"][0].get("text", "").strip(), None
                return None, "空の応答"
            else:
                return None, f"HTTP {response.status}"
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode('utf-8')
            return None, f"HTTP {e.code}: {err_body[:100]}"
        except:
            return None, f"HTTP {e.code}"
    except Exception as e:
        return None, str(e)

def execute_gemini_analysis(prompt: str, base64_images: list):
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY が設定されていません。"

    # 有効なモデル名を動的に取得
    target_models = get_available_gemini_models(GEMINI_API_KEY)
    logs = []

    for m_name in target_models:
        res_text, err = call_gemini_direct(GEMINI_API_KEY, m_name, prompt, base64_images)
        if res_text:
            return res_text, None
        logs.append(f"{m_name}: {err}")

    return None, f"Gemini解析エラー詳細: {' | '.join(logs[:3])}"

# Step 1: モデル候補3選 検出処理
def process_candidate_job(job_id: str, brand: str, category: str, base64_images: list):
    prompt = f"""
あなたは日本のプロブランド鑑定士です。
送信された画像から製品を特定し、適合する【モデル名・型番候補】を3つ抽出してJSONで返してください。

ブランド: {brand}
カテゴリ: {category}

【出力JSONフォーマット】
{{
  "candidates": [
    {{"id": 1, "title": "[型番: M44336] ルイ・ヴィトン ネオノエ MM", "desc": "モノグラム・キャンバス"}},
    {{"id": 2, "title": "[型番: M40995] ルイ・ヴィトン ネヴァーフル MM", "desc": "モノグラム トートバッグ"}},
    {{"id": 3, "title": "[型番: M45254] ルイ・ヴィトン リポーター PM", "desc": "モノグラム ショルダー"}}
  ]
}}
"""
    response_text, err_msg = execute_gemini_analysis(prompt, base64_images)
    if response_text:
        try:
            cleaned_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)
            cleaned_text = re.sub(r'```json\s*', '', cleaned_text)
            cleaned_text = re.sub(r'```\s*$', '', cleaned_text).strip()
            json_match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group(0))
                JOBS[job_id] = {"status": "completed", "data": result_data, "created_at": time.time()}
                return
        except Exception as e:
            err_msg = f"JSON解析エラー: {str(e)}"

    JOBS[job_id] = {
        "status": "completed",
        "created_at": time.time(),
        "data": {
            "candidates": [
                {"id": 1, "title": f"{brand} {category} (標準照合)", "desc": "画像から主要モデルを標準照合"},
                {"id": 2, "title": f"{brand} {category} (類似モデル)", "desc": "バリエーションモデル"},
                {"id": 3, "title": f"{brand} {category} (手入力指定)", "desc": "型番を手入力で指定"}
            ]
        }
    }

# Step 2: 鑑識＆公式定価・相場出力
def process_authentication_job(job_id: str, brand: str, category: str, model_number: str, base64_images: list):
    prompt = f"""
あなたは日本のプロ鑑定士および市場相場アナリストです。
入力情報と送信画像を比較照合し、鑑識結果と公式定価、相場をJSONで出力してください。

ブランド: {brand}
カテゴリ: {category}
型番条件: {model_number}

【出力JSONフォーマット】
{{
  "detected_model": "ルイ・ヴィトン ネオノエ MM (M44336)",
  "official_price": "272,800円 (メーカー参考定価)",
  "overall_score": 96.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・型番適合確認: 指定モデルと画像のモノグラム柄・形状は合致\\n・真贋確認: ロゴ刻印・縫製ピッチ・金具処理は基準内",
  "suspicious_points": [],
  "market_prices": {{
    "buy_store": "130,000円 ～ 150,000円",
    "fleamarket": "160,000円 ～ 180,000円",
    "auction": "145,000円 ～ 165,000円",
    "full_set_estimate": "160,000円（美品完備時）"
  }},
  "details": [
    {{"name": "1. ブランドロゴフォント・文字配置の正確性", "status": "PASS"}},
    {{"name": "2. シリアル/製造番号刻印の規則性・深さ", "status": "PASS"}},
    {{"name": "3. モノグラム/柄配置と縫製の対称性", "status": "PASS"}},
    {{"name": "4. 金具・ビス・ファスナーの仕上げとメッキ", "status": "PASS"}},
    {{"name": "5. コバ塗り（バニッシュ）の厚みと処理", "status": "PASS"}},
    {{"name": "6. 内装生地の質感とジッパー構造", "status": "PASS"}},
    {{"name": "7. ハンドル/ストラップの縫製と補強", "status": "PASS"}},
    {{"name": "8. 全体コンディションと二次流通適合度", "status": "PASS"}}
  ]
}}
"""
    response_text, err_msg = execute_gemini_analysis(prompt, base64_images)

    if response_text:
        try:
            cleaned_text = re.sub(r'<think>.*?</think>', '', response_text, flags=re.DOTALL)
            cleaned_text = re.sub(r'```json\s*', '', cleaned_text)
            cleaned_text = re.sub(r'```\s*$', '', cleaned_text).strip()

            json_match = re.search(r'\{.*\}', cleaned_text, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group(0))
                JOBS[job_id] = {"status": "completed", "data": result_data, "created_at": time.time()}
                return
        except Exception as parse_e:
            err_msg = f"JSON解析エラー: {str(parse_e)}"

    JOBS[job_id] = {
        "status": "completed",
        "created_at": time.time(),
        "data": {
            "detected_model": f"{brand} {category} (解析エラー)",
            "official_price": "-- 円",
            "overall_score": 0.0,
            "judgment": "エラー発生",
            "status_code": "ERROR",
            "message": f"【解析失敗詳細】:\n{err_msg}",
            "suspicious_points": ["Gemini AI応答の取得に失敗しました"],
            "market_prices": {"buy_store": "-- 円", "fleamarket": "-- 円", "auction": "-- 円", "full_set_estimate": "-- 円"},
            "details": []
        }
    }

@app.post("/api/v1/detect_candidates")
async def detect_candidates(
    background_tasks: BackgroundTasks,
    brand: str = Form(...),
    category: str = Form(...),
    files: List[UploadFile] = File(...)
):
    if not files or len(files) < 1:
        raise HTTPException(status_code=400, detail="画像を1枚以上送信してください。")

    base64_images = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((600, 600))
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=65)
            base64_images.append(base64.b64encode(buffered.getvalue()).decode("utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    clean_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "created_at": time.time()}

    background_tasks.add_task(process_candidate_job, job_id, brand, category, base64_images)

    return {"status": "accepted", "job_id": job_id}

@app.post("/api/v1/authenticate")
async def authenticate(
    background_tasks: BackgroundTasks,
    brand: str = Form(...),
    category: str = Form(...),
    model_number: Optional[str] = Form(""),
    files: List[UploadFile] = File(...)
):
    if not files or len(files) < 1:
        raise HTTPException(status_code=400, detail="解析用画像を1枚以上送信してください。")

    base64_images = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((600, 600))
            image = ImageEnhance.Sharpness(image).enhance(1.2)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=65)
            base64_images.append(base64.b64encode(buffered.getvalue()).decode("utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    clean_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "created_at": time.time()}

    background_tasks.add_task(process_authentication_job, job_id, brand, category, model_number, base64_images)

    return {"status": "accepted", "job_id": job_id}

@app.get("/api/v1/result/{job_id}")
def get_result(job_id: str):
    clean_old_jobs()
    if job_id not in JOBS:
        raise HTTPException(status_code=4
