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

app = FastAPI(title="Gemini 2.5 Flash Verified Authenticator Engine", version="88.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
JOBS = {}

@app.get("/")
def read_root():
    return {
        "status": "Live",
        "engine": "Gemini 2.5 Flash Verified Authenticator v88.0",
        "gemini_active": bool(GEMINI_API_KEY)
    }

def clean_old_jobs():
    now = time.time()
    expired_keys = [k for k, v in JOBS.items() if now - v.get("created_at", now) > 600]
    for k in expired_keys:
        del JOBS[k]

def process_authentication_job(job_id: str, brand: str, category: str, model_number: str, raw_bytes_list: list):
    user_hint = f"ユーザー手入力型番: {model_number}" if model_number else "ユーザー手入力型番: なし（画像から品名・型番を完全自動判別すること）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋・銀座ラシン等のプロ鑑定士および買取相場アナリストです。
送信された部位写真群（最大5枚）を画像から直接解析し、品物を特定した上で、リアルな真贋一致率スコア（0〜100%）と、その特定された品物の【日本国内における最新のリアルな実勢相場】を個別に算出してJSONで出力してください。

【対象ブランド】: {brand}
【対象カテゴリ】: {category}
【ヒント】: {user_hint}

【超重要：厳格鑑識＆画像ダイレクト識別ルール】
1. 『detected_model』:
   - 送信された画像（柄、形状、ロゴ刻印、シリアル印字等）を視覚的に直接読み取り、写っている実際の品名を正しい日本語（例: ルイ・ヴィトン ダミエ・エベヌ ジッピー・ウォレット 等）で特定してください。

2. 『market_prices』:
   - 特定した『detected_model』に基づき、日本国内の二次流通市場での適正相場をそれぞれ個別に試算してください。
     - buy_store: 買取店仕入れ目安（例: "45,000円 ～ 55,000円"）
     - fleamarket: メルカリ・ラクマ等の販売相場
     - auction: ヤフオク等の落札相場

3. 『overall_score』 / 『judgment』:
   - 根拠に基づいたリアルな一致率パーセンテージを出力してください（固定値厳禁）。

4. 『suspicious_points』:
   - 気になる微小な違和感や不審点があれば具体的に日本語配列で抽出してください。無ければ [] を返してください。

5. 『details』:
   - 画像で実際に確認できる項目のみ "PASS" または "FAIL"。写真に写っていない部位は必ず "UNCHECKED" とすること。
"""

    if not GEMINI_API_KEY:
        JOBS[job_id] = {
            "status": "completed",
            "created_at": time.time(),
            "data": {
                "detected_model": "GEMINI_API_KEY 未設定",
                "overall_score": 0.0,
                "judgment": "設定エラー",
                "status_code": "ERROR",
                "message": "RenderのEnvironmentに GEMINI_API_KEY を設定してください。",
                "suspicious_points": [],
                "market_prices": {"buy_store": "-- 円", "fleamarket": "-- 円", "auction": "-- 円"},
                "details": []
            }
        }
        return

    try:
        genai.configure(api_key=GEMINI_API_KEY)
        
        pil_images = []
        for img_bytes in raw_bytes_list:
            pil_images.append(Image.open(io.BytesIO(img_bytes)).convert('RGB'))

        generation_config = {
            "temperature": 0.2,
            "response_mime_type": "application/json",
        }

        # 404エラーを回避する現行モデル名
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            generation_config=generation_config
        )

        res = model.generate_content([prompt] + pil_images)

        if res and hasattr(res, 'text') and res.text:
            result_data = json.loads(res.text.strip())
            JOBS[job_id] = {"status": "completed", "data": result_data, "created_at": time.time()}
            return

    except Exception as e:
        JOBS[job_id] = {
            "status": "completed",
            "created_at": time.time(),
            "data": {
                "detected_model": f"{brand} {category} (解析エラー)",
                "overall_score": 0.0,
                "judgment": "エラー発生",
                "status_code": "ERROR",
                "message": f"【解析例外詳細】:\n{str(e)}",
                "suspicious_points": ["AI応答処理中に例外が発生しました"],
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

    raw_bytes_list = []
    
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((500, 500))
            image = ImageEnhance.Sharpness(image).enhance(1.2)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=75)
            raw_bytes_list.append(buffered.getvalue())
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    clean_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "created_at": time.time()}

    background_tasks.add_task(process_authentication_job, job_id, brand, category, model_number, raw_bytes_list)

    return {"status": "accepted", "job_id": job_id}

@app.get("/api/v1/result/{job_id}")
def get_result(job_id: str):
    clean_old_jobs()
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="指定のジョブが見つかりません。")
    return JOBS[job_id]
