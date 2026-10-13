import os
import io
import json
import re
import base64
import requests
from PIL import Image, ImageEnhance
from fastapi import FastAPI, Form, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from google import genai

app = FastAPI(title="Pro Precision AI Authenticator Engine", version="44.0")

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
        "engine": "Pro Precision AI Authenticator Engine v44.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

# ブランドごとのプロ鑑識チェック項目
BRAND_SPECIAL_INSTRUCTIONS = {
    "Louis Vuitton": """
・ロゴ刻印: 「LOUIS VUITTON PARIS」の「O」が完全な真円か、Rマークの位置、刻印の彫り深さとフォント間隔。
・シリアル: 製造国アルファベット2文字と製造年週（数字4桁）のフォーマット整合性。
・キャンバス/レザー: モノグラム/ダミエの目合わせ、エピ/タイガの型押しシボ感。
""",
    "Rolex": """
・文字盤: クラウンロゴの立体感・バランス、インデックスの研磨仕上げ、文字印字の立ち上がり・滲み有無。
・刻印: 6時位置ルーレット刻印（ROLEX文字とシリアル）、ラグ間リファレンス/シリアル刻印の深さ。
・ブレス/バックル: 王冠マークのエッジ・立体刻印、クラスプコード、ブレスのガタつき。
""",
    "CHANEL": """
・ロゴ/金銀箔押し: 「CHANEL」刻印のCの切り欠き角度（30度）、金箔・銀箔の剥がれや潰れ具合。
・内部シール/カード: シリアルシールのココマーク・ラメ散り・切り込み・ゴールドライン。
・金具/チェーン: ココマーク金具の右上が上・左下が上の重なり法則、金具のメッキ厚と自重。
""",
    "HERMES": """
・ステッチ: 職人による手縫い（サドルステッチ）特有の右上がり傾斜と糸の締め込み具合。
・刻印: 職人イニシャル・製造年記号刻印の押し深さ、金具の「HERMES-PARIS」刻印のシャープさ。
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
    
    # 画像前処理（シャープネス＆コントラスト強調で微小な刻印をAIに捉えさせる）
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((700, 700))
            
            # コントラストとシャープネスを適度に強調
            enhancer_c = ImageEnhance.Contrast(image)
            image = enhancer_c.enhance(1.15)
            enhancer_s = ImageEnhance.Sharpness(image)
            image = enhancer_s.enhance(1.2)

            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=80)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    user_hint = f"ユーザー指定補足型番: {model_number}" if model_number else "ユーザー指定補足型番: なし（画像から型番を完全自動特定すること）"
    brand_rule = BRAND_SPECIAL_INSTRUCTIONS.get(brand, "・ロゴフォント、シリアルフォーマット、金属研磨、素材の質感を精密検証すること。")

    prompt = f"""
あなたは日本のコメ兵・大黒屋・銀座ラシン等で数万点の真贋を鑑識してきた超一流の専任査定部長です。
提供された画像群（最大5部位）をプロ鑑識官の眼で厳格精査し、正確なJSON形式のみで出力してください。

【対象ブランド】: {brand}
【対象カテゴリ】: {category}
【ヒント】: {user_hint}

【ブランド別・極秘鑑識ルール】
{brand_rule}

【厳格鑑定ルール】
1. 『detected_model』:
   - 画像の表面・裏面・金具・シリアルを総合照合し、正確な日本語モデル名・公式型番・解読できたシリアルを出力してください。
   - 手入力型番がある場合はそれを最優先して統合してください。

2. 『overall_score』 / 『judgment』:
   - スコア判定基準を厳格化してください。
     ・95.0% 〜 100.0%: 基準内（本物判定）
     ・80.0% 〜 94.9%: 判定保留（目視推奨 / N級精巧コピーの疑いあり）
     ・80.0% 未満: 基準外（偽造品の懸念あり）

3. 『message』:
   - 判定の根拠を、必ず以下の3〜4行の箇条書き形式（プロ目線）でわかりやすく解説してください。
     「・刻印: ○○○○」
     「・シリアル: ○○○○」
     「・金具/パーツ: ○○○○」
     「・素材/構造: ○○○○」

4. 『market_prices』:
   - 該当製品の日本国内中古市場（美品コンディション）における最新実勢価格帯（買取店・フリマ・オークション）を正確に出力してください。

【出力JSONフォーマット（JSONコードブロックのみ）】
{{
  "detected_model": "ブランド名 正式ライン・製品名 (型番: XXXX / シリアル: XXXX)",
  "overall_score": 96.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・刻印: フォント・位置・押し深さ共に公式基準と完全一致\\n・シリアル: 製造国・製造年週コードのフォーマット適合\\n・金具: ジッパー/ロゴのエッジ処理およびメッキ質感が極めて良好\\n・素材: 生地目・アライメントに歪みなし",
  "market_prices": {{
    "buy_store": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円",
    "fleamarket": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円",
    "auction": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円"
  }},
  "details": [
    {{"name": "ロゴフォント・刻印配置の正確性", "pass": true}},
    {{"name": "素材仕上げ・研磨・バリ処理の質感", "pass": true}},
    {{"name": "シリアル/製造番号のフォーマット適合", "pass": true}},
    {{"name": "細部構造・金具部品の基準一致", "pass": true}}
  ]
}}
"""

    response_text = None
    last_err = None

    # --- 1フェーズ: Gemini API ---
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

    # --- 2フェーズ: OpenRouter API ---
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
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=or_payload, timeout=20)
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
        "market_prices": {"buy_store": "算出不能", "fleamarket": "算出不能", "auction": "算出不能"},
        "details": [
            {"name": "ロゴフォント・刻印配置の正確性", "pass": False},
            {"name": "素材仕上げ・研磨・バリ処理の質感", "pass": False},
            {"name": "シリアル/製造番号のフォーマット適合", "pass": False},
            {"name": "細部構造・金具部品の基準一致", "pass": False}
        ]
    }

    if not response_text:
        return fallback_response

    try:
        clean_json = re.sub(r'```json\s*|\s*```', '', response_text).strip()
        result_data = json.loads(clean_json)
        return result_data
    except Exception:
        return fallback_response
