import os
import io
import json
import re
import base64
import requests
from PIL import Image, ImageEnhance, ImageFilter
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from google import genai

app = FastAPI(title="Hyper-Fast Strict AI Authenticator Engine", version="49.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

@app.get("/")
def read_root():
    return {
        "status": "Live",
        "engine": "Hyper-Fast Strict AI Authenticator Engine v49.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

STRICT_AUTHENTICATION_SPECS = {
    "Louis Vuitton": """
・ロゴ打刻: 「LOUIS VUITTON PARIS」の「O」が完全な真円か。「N」の両端先端のシャープさ、刻印の底面平坦度。1つでもフォントが太かったり潰れていたら即異変判定。
・シリアル: 製造国アルファベット2文字と製造年週（1/3桁目が週、2/4桁目が年）の法則性適合。書体の打刻深さズレがあれば即異変判定。
・縫製/コバ: 黄色ステッチの15度斜め傾斜目打ち、角のピッチ崩れ、コバ塗料のはみ出しや不透明感があれば即異変判定。
・金具: ビスやジッパーのLVロゴエッジ面のバリ、粗いメッキ処理があれば即異変判定。
""",
    "Rolex": """
・王冠マーク: 5本の指の丸みバランス、基部楕円線の細さ。印刷滲みがあれば即異変判定。
・ダイアル印字: インクの立体盛り上がり、針の側面バリ、インデックス位置ズレがあれば即異変判定。
・ルーレット刻印: ベゼル内周の「ROLEX」文字の「X」交差部とシリアル数字の刻印深さ不均一は即異変判定。
・ガラス透かし: 6時位置レーザー王冠のドット大きすぎや不自然な目立ちがあれば即異変判定。
""",
    "CHANEL": """
・CC金具: 「右上が上、左下が上」の重なり法則から1ミリでも外れていたら即偽造品判定。
・シール/カード: シリアルシールのラメ不均一、ココマーク透かし・切り込み欠如は即異変判定。
・レザー: キルティングの1インチあたり目数不足、革の不自然な硬さは即異変判定。
""",
    "HERMES": """
・サドルステッチ: 職人の手縫い特有の「右上がり斜め傾斜」。ミシン縫いのような平行・直線は即異変判定。
・刻印: 箔押しの金銀密着度、職人マーク・年式刻印の押し圧不均一は即異変判定。
・金具: マイナスネジ頭の溝仕上げ、プレート「HERMES-PARIS」刻印の線ブレは即異変判定。
"""
}

@app.post("/api/v1/authenticate")
async def authenticate(
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
    
    # 爆速レスポンス化のための最適解像度処理 (550px, 高画質圧縮)
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((550, 550))
            
            # AI識別用エッジ強調処理
            image = ImageEnhance.Contrast(image).enhance(1.25)
            image = ImageEnhance.Sharpness(image).enhance(1.3)

            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=75)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    user_hint = f"ユーザー指定補足型番: {model_number}" if model_number else "ユーザー指定補足型番: なし（画像解析により完全自動特定）"
    strict_spec = STRICT_AUTHENTICATION_SPECS.get(brand, "・ロゴフォント、シリアル法則、金具研磨、ステッチ、コバ塗りのわずかな異変も一切見落とさず厳格判定すること。")

    prompt = f"""
あなたは日本のコメ兵・大黒屋・銀座ラシン等の最高峰ブランド鑑識主任です。
提供された画像群（最大5部位）を厳格精査し、0.1ミリの異変や不整合も絶対に見逃さずJSON形式のみで爆速出力してください。

【対象ブランド】: {brand}
【対象カテゴリ】: {category}
【ヒント】: {user_hint}

【ブランド別・超厳格チェック指針】
{strict_spec}

【ゼロ・トレランス判定＆不審箇所提示ルール】
1. 『suspicious_points』:
   - 異変や不自然な部位（ロゴの『O』の歪み、メッキの粗さ、シリアル打ち刻みの浅さ等）を配列形式で抽出。完品は `[]` を返却。
2. 『overall_score』 / 『judgment』:
   - 98.0%〜100.0%: 基準内 / 85.0%〜97.9%: 判定保留 / 85.0%未満: 基準外。1項目でも『pass: false』があれば絶対に基準内にしないこと。

【出力JSONフォーマット（JSONコードブロックのみ）】
{{
  "detected_model": "ブランド名 正式ライン・製品名 (型番: XXXX / シリアル: XXXX)",
  "overall_score": 98.5,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・刻印・フォント精度: 基準適合\\n・シリアル適合度: 基準適合\\n・金具・メッキ仕上げ: 基準適合\\n・縫製・コバ・質感: 基準適合",
  "suspicious_points": [],
  "market_prices": {{
    "buy_store": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円",
    "fleamarket": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円",
    "auction": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円"
  }},
  "details": [
    {{"name": "1. ロゴフォントの真円性・文字間隔の正確性", "pass": true}},
    {{"name": "2. ®マーク・製造国刻印の凹み形状と底面平坦度", "pass": true}},
    {{"name": "3. シリアル/製造番号の打刻書体・年週法則適合性", "pass": true}},
    {{"name": "4. 金属パーツのエッジ面取り・メッキ層の均一性", "pass": true}},
    {{"name": "5. ビス・ねじ頭のすり割り形状・溝の仕上げ状態", "pass": true}},
    {{"name": "6. ジッパー・スナップ金具の刻印・噛み合わせ", "pass": true}},
    {{"name": "7. ステッチ（縫い目）の目打ち傾斜角度・ピッチ", "pass": true}},
    {{"name": "8. 素材（レザー/キャンバス）のシボ・柄アライメント", "pass": true}},
    {{"name": "9. コバ処理（バニッシュ塗料の透明度・厚み）", "pass": true}},
    {{"name": "10. 内側ライニング・裁断面・生地張り質感", "pass": true}},
    {{"name": "11. ギャランティ/シリアルシールのラメ・透かし構造", "pass": true}},
    {{"name": "12. 全体構造の歪み・自重・各パーツの取付角度", "pass": true}}
  ]
}}
"""

    response_text = None
    last_err = None

    if GEMINI_API_KEY:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            res = client.models.generate_content(
                model='gemini-3.8-flash',
                contents=[prompt] + pil_images,
            )
            if res and res.text:
                response_text = res.text.strip()
        except Exception as e:
            last_err = f"Gemini Limit: {str(e)}"

    if not response_text and OPENROUTER_API_KEY:
        openrouter_models = [
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.2-11b-vision-instruct:free",
            "openrouter/free"
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
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=or_payload, timeout=12)
                if res.status_code == 200:
                    res_json = res.json()
                    if "choices" in res_json and len(res_json["choices"]) > 0:
                        content = res_json["choices"][0]["message"]["content"]
                        if content and len(content.strip()) > 0:
                            response_text = content.strip()
                            break
                last_err = f"OpenRouter ({or_model}: {res.status_code})"
            except Exception as e:
                last_err = f"OpenRouter Err: {str(e)}"

    fallback_response = {
        "detected_model": model_number or "解析一時保留（型番自動特定中）",
        "overall_score": 75.0,
        "judgment": "判定保留（一時混雑）",
        "status_code": "REVIEW",
        "message": f"解析が一時的に混雑しています。再度査定ボタンを押してください: {str(last_err)}",
        "suspicious_points": ["解析処理タイムアウトによる確認保留"],
        "market_prices": {"buy_store": "算出不能", "fleamarket": "算出不能", "auction": "算出不能"},
        "details": [
            {"name": "1. ロゴフォントの真円性・文字間隔の正確性", "pass": False},
            {"name": "2. ®マーク・製造国刻印の凹み形状と底面平坦度", "pass": False},
            {"name": "3. シリアル/製造番号の打刻書体・年週法則適合性", "pass": False},
            {"name": "4. 金属パーツのエッジ面取り・メッキ層の均一性", "pass": False},
            {"name": "5. ビス・ねじ頭のすり割り形状・溝の仕上げ状態", "pass": False},
            {"name": "6. ジッパー・スナップ金具の刻印・噛み合わせ", "pass": False},
            {"name": "7. ステッチ（縫い目）の目打ち傾斜角度・ピッチ", "pass": False},
            {"name": "8. 素材（レザー/キャンバス）のシボ・柄アライメント", "pass": False},
            {"name": "9. コバ処理（バニッシュ塗料の透明度・厚み）", "pass": False},
            {"name": "10. 内側ライニング・裁断面・生地張り質感", "pass": False},
            {"name": "11. ギャランティ/シリアルシールのラメ・透かし構造", "pass": False},
            {"name": "12. 全体構造の歪み・自重・各パーツの取付角度", "pass": False}
        ]
    }

    if not response_text:
        return fallback_response

    try:
        clean_json = re.sub(r'```json\s*|\s*```', '', response_text).strip()
        result_data = json.loads(clean_json)

        if "details" in result_data and isinstance(result_data["details"], list):
            has_failed_item = any(item.get("pass") is False for item in result_data["details"])
            if has_failed_item:
                if result_data.get("overall_score", 100) >= 98.0:
                    result_data["overall_score"] = 92.0
                if result_data.get("judgment") == "基準内":
                    result_data["judgment"] = "判定保留（要目視査定）"

        return result_data
    except Exception:
        return fallback_response
