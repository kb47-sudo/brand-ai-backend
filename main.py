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

app = FastAPI(title="Ultra-Precision AI Authenticator Engine", version="45.0")

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
        "engine": "Ultra-Precision AI Authenticator Engine v45.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

# ブランド別・超高精度真贋マニュアル
BRAND_DEEP_INSTRUCTIONS = {
    "Louis Vuitton": """
・刻印: 「LOUIS VUITTON PARIS」の「O」が縦長ではなく完全な真円か。「N」の両端がシャープか。「made in France」等のフォント深さが均一か。
・シリアル: 製造国コード（AA, AR, BA, FL, MB, SP, TH, VI等）と製造年週（1/3桁目が週、2/4桁目が年）の法則性が正確か。
・金具/ジッパー: LVロゴの角が鋭利に面取りされているか。メッキに粗い気泡やはげがないか。
・生地/コバ: モノグラム/ダミエの整列アライメント、コバ（バニッシュ）塗りの厚みとはみ出し有無。
""",
    "Rolex": """
・文字盤: クラウンマーク（王冠）の5本の指の先端と基部のバランス、ROLEX文字の立体的なインク盛り、インデックスの仕上げ。
・刻印: 6時位置インナーリング（ルーレット）の「ROLEX」刻印およびシリアル、ケースラグ間のRef/シリアル刻印の深さ。
・王冠透かし: 6時位置サファイアガラスの王冠レーザー刻印（小さく緻密か）。
・ブレス/バックル: クラスプ裏の王冠マークの立体感、刻印の粗さ、ブレスの隙間・ガタつき。
""",
    "CHANEL": """
・ロゴ刻印: 「CHANEL」のCの切り欠き角度（30度）、文字の厚みと箔押し（ゴールド/シルバー）の歪み。
・ブティックシール/カード: シリアルシールのココマーク・ゴールドラメの散り具合・透かし・切り込みの有無。
・CC金具: 右上のココマークが上、左下のココマークが上という重なり法則、金具の自重と質感。
""",
    "HERMES": """
・ステッチ: 職人の手縫い（サドルステッチ）特有の右上がり斜め目打ち。糸のピッチと締め込みの均一性。
・刻印: 「HERMES PARIS MADE IN FRANCE」の職人イニシャル・製造年記号刻印（□や○、近年はアルファベット単体）の打刻状態。
・金具: カデナ・底鋲・プレートのメッキの深み、「HERMES-PARIS」刻印のエッジ。
""",
    "GUCCI": """
・ロゴ刻印: 「GUCCI made in italy」のGとCの丸み、Rマークの円の大きさ。
・シリアル: 背面タグ裏の数字刻印（上が型番、下が工場コード）の独特な打刻フォント（数字の跳ね）。
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
    
    # 画像デジタル高度処理（輪郭エッジ・コントラスト自動調整）
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            image.thumbnail((800, 800))
            
            # コントラスト＆シャープネス（輪郭抽出強化）
            image = ImageEnhance.Contrast(image).enhance(1.25)
            image = ImageEnhance.Sharpness(image).enhance(1.3)
            image = image.filter(ImageFilter.DETAIL)

            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=85)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    user_hint = f"ユーザー指定補足型番: {model_number}" if model_number else "ユーザー指定補足型番: なし（画像解析により完全自動特定）"
    deep_rule = BRAND_DEEP_INSTRUCTIONS.get(brand, "・ロゴフォント精度、シリアル法則性、金具研磨、ステッチ、コバ塗りを極小レベルで鑑識すること。")

    prompt = f"""
あなたは日本のコメ兵・大黒屋・Ginza Rasin・ブランドオフ等で長年真贋鑑識を担当してきた「最高峰ブランド鑑定鑑識官」です。
提供された画像（最大5部位）を顕微鏡レベルの厳しさで査定し、不審点・違和感を徹底的に検証した上でJSON形式のみで出力してください。

【対象ブランド】: {brand}
【対象カテゴリ】: {category}
【ヒント】: {user_hint}

【ブランド別・極秘鑑識基準】
{deep_rule}

【絶対鑑定ルール】
1. 『detected_model』:
   - 表面・裏面構造・刻印・金具・シリアルから製品名・公式型番・解読できたシリアルをピンポイントで特定してください。
   - 手入力型番がある場合は第一優先として統合してください。

2. 『overall_score』 / 『judgment』:
   - 真贋判定閾値を厳格化してください：
     ・96.0% 〜 100.0%: 基準内（本物確定）
     ・85.0% 〜 95.9%: 判定保留（精巧N級コピーの懸念・目視査定推奨）
     ・85.0% 未満: 基準外（偽造品の疑い極めて大）

3. 『message』:
   - 鑑識結果の根拠を、以下の形式で詳細にプロの解説を作成してください（改行 \\n を使用）：
     「・刻印フォント: ○○○○」
     「・シリアル適合性: ○○○○」
     「・金具/ビス仕上げ: ○○○○」
     「・素材/縫製/コバ: ○○○○」

4. 『details』（10大詳細チェックリスト）:
   - 以下の10項目について、それぞれpass（true/false）を評価してください。

【出力JSONフォーマット（JSONのみ出力）】
{{
  "detected_model": "ブランド名 正式ライン・製品名 (型番: XXXX / シリアル: XXXX)",
  "overall_score": 97.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・刻印フォント: ロゴ「O」の真円性、PARIS文字の刻み深さが公式基準に合致\\n・シリアル適合性: 製造国コードおよび年週番号のフォーマット適合\\n・金具/ビス仕上げ: ジッパーロゴのエッジ処理、メッキ厚が良好\\n・素材/縫製/コバ: コバ塗りの厚みが均一でステッチピッチに崩れなし",
  "market_prices": {{
    "buy_store": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円",
    "fleamarket": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円",
    "auction": "◯◯,◯◯◯円 ～ ◯◯,◯◯◯円"
  }},
  "details": [
    {{"name": "1. ブランドロゴフォント・文字間隔の正確性", "pass": true}},
    {{"name": "2. ®マーク・製造国刻印の深さと形状", "pass": true}},
    {{"name": "3. シリアル/製造番号のフォーマット適合", "pass": true}},
    {{"name": "4. 金属パーツの研磨・面取り・メッキ質感", "pass": true}},
    {{"name": "5. ビス・ねじ頭の形状・溝の仕上げ", "pass": true}},
    {{"name": "6. ジッパー・スナップ金具の刻印・エッジ", "pass": true}},
    {{"name": "7. ステッチ（縫い目）のピッチ・傾斜処理", "pass": true}},
    {{"name": "8. 素材（レザー/キャンバス）の目・シボ感", "pass": true}},
    {{"name": "9. コバ処理（塗料厚み・はみ出し・色合い）", "pass": true}},
    {{"name": "10. 内側ライニング・生地・シールの質感", "pass": true}}
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
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=or_payload, timeout=22)
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
        "market_prices": {"buy_store": "算出不能", "
