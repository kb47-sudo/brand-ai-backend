import os
import io
import json
import re
import uuid
import time
from PIL import Image, ImageEnhance
from fastapi import FastAPI, Form, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import google.generativeai as genai

app = FastAPI(title="Pro Authenticator Engine (Gemini Dedicated)", version="138.0")

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
        "engine": "Pro Authenticator Engine v138.0 (Gemini Dedicated)",
        "gemini_active": bool(GEMINI_API_KEY)
    }

def clean_old_jobs():
    now = time.time()
    for k in list(JOBS.keys()):
        if now - JOBS[k].get("created_at", now) > 900:
            JOBS.pop(k, None)

def execute_gemini_analysis(prompt: str, pil_images: list):
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY が設定されていません。"

    logs = []
    try:
        genai.configure(api_key=GEMINI_API_KEY)
        config = genai.types.GenerationConfig(
            temperature=0.1,
            response_mime_type="application/json"
        )
        
        # 安定動作するGemini公式モデルで順次実行
        for g_model in ["gemini-1.5-flash", "gemini-1.5-pro"]:
            try:
                model = genai.GenerativeModel(model_name=g_model, generation_config=config)
                res = model.generate_content([prompt] + pil_images)
                if res and hasattr(res, 'text') and res.text:
                    return res.text.strip(), None
            except Exception as g_err:
                logs.append(f"{g_model}: {str(g_err)}")
    except Exception as e:
        logs.append(f"GeminiInitError: {str(e)}")

    return None, f"Gemini解析エラー詳細: {' | '.join(logs)}"

# Step 1: モデル候補3選 検出処理
def process_candidate_job(job_id: str, brand: str, category: str, pil_images: list):
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
    response_text, err_msg = execute_gemini_analysis(prompt, pil_images)
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
def process_authentication_job(job_id: str, brand: str, category: str, model_number: str, pil_images: list):
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
    response_text, err_msg = execute_gemini_analysis(prompt, pil_images)

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

    pil_images = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((600, 600))
            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=65)
            pil_images.append(Image.open(io.BytesIO(buffered.getvalue())))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    clean_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "created_at": time.time()}

    background_tasks.add_task(process_candidate_job, job_id, brand, category, pil_images)

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

    pil_images = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((600, 600))
            image = ImageEnhance.Sharpness(image).enhance(1.2)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=65)
            pil_images.append(Image.open(io.BytesIO(buffered.getvalue())))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    clean_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "created_at": time.time()}

    background_tasks.add_task(process_authentication_job, job_id, brand, category, model_number, pil_images)

    return {"status": "accepted", "job_id": job_id}

@app.get("/api/v1/result/{job_id}")
def get_result(job_id: str):
    clean_old_jobs()
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="指定のジョブが見つかりません。")
    return JOBS[job_id]
