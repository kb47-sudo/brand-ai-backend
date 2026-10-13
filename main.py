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

app = FastAPI(title="Multi-AI Fallback Engine", version="107.0")

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
        "engine": "Multi-AI Fallback Engine v107.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

def clean_old_jobs():
    now = time.time()
    expired_keys = [k for k, v in JOBS.items() if now - v.get("created_at", now) > 600]
    for k in expired_keys:
        del JOBS[k]

def http_post_json(url: str, headers: dict, data_dict: dict, timeout: int = 15):
    try:
        json_bytes = json.dumps(data_dict).encode('utf-8')
        req = urllib.request.Request(url, data=json_bytes, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status == 200:
                res_body = response.read().decode('utf-8')
                return json.loads(res_body)
    except Exception as e:
        print(f"HTTP Request Error ({url}): {e}")
    return None

def execute_multi_ai_analysis(prompt: str, pil_images: list, base64_images: list):
    # --- 第1フェーズ: Gemini API (最新推奨モデル) ---
    if GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            generation_config = {
                "temperature": 0.2,
                "response_mime_type": "application/json",
            }
            # 現在利用可能な主要モデル
            gemini_candidate_models = [
                "gemini-2.0-flash",
                "gemini-2.5-flash",
                "gemini-1.5-flash-latest"
            ]
            for g_model in gemini_candidate_models:
                try:
                    model = genai.GenerativeModel(
                        model_name=g_model,
                        generation_config=generation_config
                    )
                    res = model.generate_content([prompt] + pil_images)
                    if res and hasattr(res, 'text') and res.text:
                        return res.text.strip(), None
                except Exception as g_err:
                    print(f"Gemini Model {g_model} Error: {g_err}")
        except Exception as e:
            print(f"Gemini Init Error: {e}")

    # --- 第2フェーズ: OpenRouter API ---
    if OPENROUTER_API_KEY and base64_images:
        openrouter_models = [
            "google/gemini-2.0-flash-001",
            "meta-llama/llama-3.2-11b-vision-instruct",
            "qwen/qwen-2-vl-72b-instruct"
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
            or_payload = {
                "model": or_model,
                "messages": [{"role": "user", "content": content_payload}]
            }
            res_json = http_post_json("https://openrouter.ai/api/v1/chat/completions", headers, or_payload, timeout=15)
            if res_json and "choices" in res_json and len(res_json["choices"]) > 0:
                content = res_json["choices"][0]["message"]["content"]
                if content and len(content.strip()) > 0:
                    return content.strip(), None

    # --- 第3フェーズ: Groq API (正式ビジョンモデル) ---
    if GROQ_API_KEY and base64_images:
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
            "model": "llama-3.2-11b-vision-instruct",
            "messages": [{"role": "user", "content": content_payload}]
        }
        res_json = http_post_json("https://api.groq.com/openai/v1/chat/completions", headers, groq_payload, timeout=12)
        if res_json and "choices" in res_json and len(res_json["choices"]) > 0:
            content = res_json["choices"][0]["message"]["content"]
            if content and len(content.strip()) > 0:
                return content.strip(), None

    return None, "全AIエンジン（Gemini, OpenRouter, Groq）の接続試行が失敗または制限に達しました。"

def process_authentication_job(job_id: str, brand: str, category: str, model_number: str, raw_bytes_list: list, base64_images: list, pil_images: list):
    user_hint = f"ユーザー手入力型番: {model_number}" if model_number else "ユーザー手入力型番: なし（画像から品名・型番を完全自動判別すること）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋・銀座ラシン等のプロ鑑定士および買取相場アナリストです。
送信された部位写真群（最大5枚）を画像から直接解析し、品物を特定した上で、リアルな真贋一致率スコア（0〜100%）と、その特定された品物の【日本国内における最新のリアルな実勢相場】を個別に算出してJSON形式でのみ出力してください。

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

【出力JSONフォーマット例】
{{
  "detected_model": "ルイ・ヴィトン ダミエ ジッピー・ウォレット",
  "overall_score": 95.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・刻印精度: 基準内\\n・シリアル適合度: 適合",
  "suspicious_points": [],
  "market_prices": {{
    "buy_store": "45,000円 ～ 55,000円",
    "fleamarket": "60,000円 ～ 70,000円",
    "auction": "50,000円 ～ 62,000円"
  }},
  "details": [
    {{"name": "1. ロゴフォントの真円性・文字間隔の正確性", "status": "PASS"}}
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

    raw_bytes_list = []
    base64_images = []
    pil_images = []
    
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((600, 600))
            image = ImageEnhance.Sharpness(image).enhance(1.2)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=75)
            img_bytes = buffered.getvalue()
            
            raw_bytes_list.append(img_bytes)
            pil_images.append(Image.open(io.BytesIO(img_bytes)))
            base64_images.append(base64.b64encode(img_bytes).decode("utf-8"))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    clean_old_jobs()
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {"status": "processing", "created_at": time.time()}

    background_tasks.add_task(process_authentication_job, job_id, brand, category, model_number, raw_bytes_list, base64_images, pil_images)

    return {"status": "accepted", "job_id": job_id}

@app.get("/api/v1/result/{job_id}")
def get_result(job_id: str):
    clean_old_jobs()
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="指定のジョブが見つかりません。")
    return JOBS[job_id]
