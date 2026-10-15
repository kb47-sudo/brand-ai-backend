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

app = FastAPI(title="Pro Authenticator & Market Valuation Engine", version="133.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

JOBS = {}

@app.get("/")
def read_root():
    return {
        "status": "Live",
        "engine": "Pro Authenticator Strict Engine v133.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

def clean_old_jobs():
    now = time.time()
    for k in list(JOBS.keys()):
        if now - JOBS[k].get("created_at", now) > 900:
            JOBS.pop(k, None)

def http_post_json(url: str, headers: dict, data_dict: dict, timeout: int = 30):
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
                "temperature": 0.0,
                "response_mime_type": "application/json"
            }
            for g_model in ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]:
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
            res_json, err = http_post_json("https://openrouter.ai/ai/v1/chat/completions", headers, or_payload, timeout=25)
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
        
        for groq_model in ["llama-3.2-11b-vision-instruct", "llama-3.3-70b-versatile"]:
            groq_payload = {
                "model": groq_model,
                "messages": [{"role": "user", "content": content_payload}]
            }
            res_json, err = http_post_json("https://api.groq.com/openai/v1/chat/completions", headers, groq_payload, timeout=20)
            if res_json and "choices" in res_json and len(res_json["choices"]) > 0:
                content = res_json["choices"][0]["message"]["content"]
                if content and len(content.strip()) > 0:
                    return content.strip(), None
            logs.append(f"Groq({groq_model}): {err or 'Empty'}")

    return None, f"全AI接続失敗詳細: {' | '.join(logs)}"

# Step 1: モデル候補3選 検出処理
def process_candidate_job(job_id: str, brand: str, category: str, base64_images: list, pil_images: list):
    prompt = f"""
あなたは日本の大手買取店（コメ兵、大黒屋、コミット銀座、ジャックロード）で20年以上の鑑識歴を持つ「最高峰プロ鑑定士」です。
送信された画像からモデルを特定し、適合する【モデル名・型番候補】を3つ抽出してJSON形式で返してください。

【ブランド】: {brand}
【カテゴリ】: {category}

【厳格出力JSONフォーマット】
{{
  "candidates": [
    {{"id": 1, "title": "[型番: Ref.126610LN] ロレックス サブマリーナー デイト", "desc": "黒文字盤・セラクロムベゼル・現行41mm"}},
    {{"id": 2, "title": "[型番: Ref.116610LN] ロレックス サブマリーナー デイト", "desc": "黒文字盤・旧型40mm"}},
    {{"id": 3, "title": "[型番: Ref.124060] ロレックス サブマリーナー (ノンデイト)", "desc": "黒文字盤・デイト表示なし"}}
  ]
}}
"""
    response_text, err_msg = execute_multi_ai_analysis(prompt, pil_images, base64_images)
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
            err_msg = f"候補抽出し解析エラー: {str(e)}"

    JOBS[job_id] = {
        "status": "completed",
        "created_at": time.time(),
        "data": {
            "candidates": [
                {"id": 1, "title": f"{brand} {category} (標準型番特定)", "desc": "画像から主要モデルを標準照合"},
                {"id": 2, "title": f"{brand} {category} (類似モデルA)", "desc": "別バリエーション"},
                {"id": 3, "title": f"{brand} {category} (手入力・自由指定)", "desc": "型番を手入力で指定"}
            ]
        }
    }

# Step 2: 超厳格真贋鑑識 ＆ 公式定価＋動的相場出力
def process_authentication_job(job_id: str, brand: str, category: str, model_number: str, base64_images: list, pil_images: list):
    prompt = f"""
あなたは日本のコメ兵、大黒屋、銀座ラシン、コミット銀座等で20年以上の鑑定歴を持つ「超厳格なプロ真贋鑑識官」および市場相場アナリストです。

【指定情報】
- ブランド: {brand}
- カテゴリ: {category}
- 選択/指定型番・条件: {model_number}

【超厳格 真贋判定プロトコル（※判定基準を極限まで厳しくすること）】
1. 『真贋チェック基準』:
   - 偽物（Super Clone / 1:1 コピー / 精巧スーパーコピー）の流入を防ぐため、微細なポイントまで超厳格に監査すること。
   - 以下の部位に少しでもフォントの乱れ、エッジの甘さ、印字の滲み、刻印の深さ・形状の不自然さ、金属仕上げ（コバ・ポリッシュ・サテン）のチープさがある場合は、躊躇なく「判定: 注意」または「判定: 基準外」とし、scoreを下げてください。
     ① ブランドロゴフォント（文字間隔、真円性、OやS等のエッジ）
     ② シリアル/Ref型番刻印（レーザー刻印の深さ、打ち込みの質感、文字揃い）
     ③ 文字盤/キャンバス印刷（インデックス配置、ダイヤル印字の立体感）
     ④ 金具/カシメ/ビス（ネジ山の精度、メッキの輝きとバリ、彫り込み精度）
     ⑤ 縫製/ステッチ（針目の角度、ピッチ間隔、糸の太さと始末）
     ⑥ 素材質感/コバ塗り（レザーのしなやかさ、コバ塗り塗膜の厚みと塗ムラ）

2. 『suspicious_points（不審・懸念箇所の箇条書き出力）』:
   - 違和感・基準不適合の可能性がある場合、その具体的な理由（例: 「ロゴフォントの『O』の真円率が低く印字が甘い」「ルーレット刻印の文字深さが浅い」「カシメ金具に微細なバリが見受けられる」等）を『suspicious_points』配列に最大3項目まで明記すること。
   - 100%基準内と確信できる場合のみ空配列 `[]` とすること。

3. 『judgment & overall_score』:
   - 100%基準内かつ高品質: judgment="基準内", status_code="PASS", score=92.0～99.0
   - わずかでも違和感・写真不鮮明あり: judgment="注意", status_code="WARNING", score=70.0～84.0
   - 明らかな偽物・基準不適合: judgment="基準外", status_code="FAIL", score=10.0～59.0

4. 『official_price & market_prices』:
   - 日本国内メーカー公式参考定価（税込）を算定。
   - 買取店仕入れ目安、フリマ相場、オークション相場、付属品完備時上限を正確に出力。

【出力JSONフォーマット】
{{
  "detected_model": "[型番: Ref.126610LN] ロレックス サブマリーナー デイト (型番適合OK)",
  "official_price": "1,558,700円 (メーカー参考定価)",
  "overall_score": 96.5,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・型番適合確認: 指定されたRef.126610LNと画像の黒文字盤・セラクロムベゼル仕様は完全合致\\n・真贋鑑識結果: 6時位置ルーレット刻印、クラウンロゴ、クラスプ内部彫り込みのフォントおよび深さはメーカー基準に適合\\n・定価比較: メーカー参考定価1,558,700円に対し、二次流通プレ値市場を形成",
  "suspicious_points": [],
  "market_prices": {{
    "buy_store": "1,950,000円 ～ 2,100,000円",
    "fleamarket": "2,200,000円 ～ 2,400,000円",
    "auction": "2,050,000円 ～ 2,200,000円",
    "full_set_estimate": "2,250,000円（付属品完備・Sランク時）"
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
            "suspicious_points": ["AI応答の取得に失敗しました"],
            "market_prices": {"buy_store": "-- 円", "fleamarket": "-- 円", "auction": "-- 円", "full_set_estimate": "-- 円"},
            "details": []
        }
    }

# Step 1 API (型番3選抽出)
@app.post("/api/v1/detect_candidates")
async def detect_candidates(
    background_tasks: BackgroundTasks,
    brand: str = Form(...),
    category: str = Form(...),
    files: List[UploadFile] = File(...)
):
    if not files or len(files) < 1:
        raise HTTPException(status_code=400, detail="全体写真を1枚以上送信してください。")

    base64_images = []
    pil_images = []
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((600, 600))
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

    background_tasks.add_task(process_candidate_job, job_id, brand, category, base64_images, pil_images)

    return {"status": "accepted", "job_id": job_id}

# Step 2 API (超厳格鑑識＆公式定価＋相場出力)
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
