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

app = FastAPI(title="Hyper-Precision Micro AI Authenticator", version="46.0")

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
        "engine": "Hyper-Precision Micro AI Authenticator Engine v46.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

# 超精密真贋マニュアル
DEEP_AUTHENTICATION_SPECS = {
    "Louis Vuitton": """
・ロゴ打刻: 「LOUIS VUITTON PARIS」の「O」が完全真円か、「L」の横棒の短さ、「S」の上半分の縮小バランス、刻印文字の底部底面の平坦さ。
・シリアル/製造刻印: 2文字＋4桁数字の打刻深度とフォント形状。特に「1」の頭のフック感や「4」の上の開き。
・縫製/ステッチ: 黄色いシーム糸の目打ち傾斜角度（約15度）、角部分の巻き込み縫いの目数。
・コバ/ビス: ビスヘッドのLVロゴの盛り上がりと刻印凹みのシャープさ、コバ塗料の透明度と赤みの色合い。
""",
    "Rolex": """
・王冠マーク: 5本の先端円形部分のサイズ均一性、基部の楕円線の細さ。
・ダイアル印字: 文字盤インクのぷっくりとした立体感（シルクスクリーン印刷特有の盛り上がり）、針の側面研磨のバリの有無。
・ルーレット刻印: ベゼル内周の「ROLEX」文字の「X」の交差線とシリアル数字の刻印深さ。
・ガラス透かし: 6時位置のレーザー刻印王冠（ドットの離れ具合、肉眼では見えにくい微細ドット構造）。
""",
    "CHANEL": """
・CCマーク金具: 右上が上、左下が上という交差規則。金属のエッジが立ちすぎておらず滑らかな面取りがなされているか。
・シール/カード: ゴールドラメの粒子サイズ不均一性、シリアルナンバーのフォント（特に「1」の足の有無、「0」の斜め線の有無）。
・マトラッセ革: キルティングのステッチピッチ（1インチあたりの目数）と革の自然なふくらみ。
""",
    "HERMES": """
・手縫いステッチ: サドルステッチ（2本針交差手縫い）特有の右上がり傾斜。ミシン縫いのような直線・平行感がないこと。
・刻印: 箔押しの金銀の粒子密着度、職人マーク・年式刻印の押し圧による革のへこみ方。
・金具: プレートのネジ頭がマイナスネジであること、カデナの自重と「HERMES」文字のフォント仕上げ。
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
    
    # 高度ミクロ画像前処理（輪郭強調＆局所解像度向上）
    for file in files:
        contents = await file.read()
        try:
            image = Image.open(io.BytesIO(contents)).convert('RGB')
            
            # 微細刻印読取用の解像度調整 (900px)
            image.thumbnail((900, 900))
            
            # ミクロディテール強調（コントラスト、シャープネス、輪郭強調）
            image = ImageEnhance.Contrast(image).enhance(1.3)
            image = ImageEnhance.Sharpness(image).enhance(1.4)
            image = image.filter(ImageFilter.EDGE_ENHANCE)

            pil_images.append(image)

            buffered = io.BytesIO()
            image.save(buffered, format="JPEG", quality=88)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            base64_images.append(img_str)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"画像処理エラー: {str(e)}")

    user_hint = f"ユーザー指定補足型番: {model_number}" if model_number else "ユーザー指定補足型番: なし（画像解析により完全自動特定）"
    deep_spec = DEEP_AUTHENTICATION_SPECS.get(brand, "・ロゴフォント、シリアル法則性、金具研磨、ステッチ、コバ塗りを極小ミクロレベルで鑑識すること。")

    prompt = f"""
あなたはコメ兵・大黒屋・銀座ラシン等の鑑定部門で数万点の真贋を鑑識してきた「顕微鏡レベルの超エキスパート鑑識官」です。
提供された画像（最大5部位）をミクロ視点で厳格査定し、0.1mmレベルの微小な違和感や不整合も一切見逃さずに検証した上でJSON形式のみで出力してください。

【対象ブランド】: {brand}
【対象カテゴリ】: {category}
【ヒント】: {user_hint}

【ブランド別・ミクロ超詳細鑑識基準】
{deep_spec}

【厳格ネガティブ鑑識ルール】
1. 『detected_model』:
   - 正確な日本語モデル名・公式型番・解読できたシリアルを特定して出力してください。

2. 『overall_score』 / 『judgment』:
   - 判定基準を極限まで厳格化してください：
     ・97.0% 〜 100.0%: 基準内（極めて高い本物精度）
     ・88.0% 〜 96.9%: 判定保留（精巧スーパーコピーの疑いあり・要目視確認）
     ・88.0% 未満: 基準外（偽造品の懸念大）

3. 『message』:
   - 鑑識根拠を以下のプロ解説フォーマット（箇条書き）で詳細に作成してください（改行 \\n を使用）：
     「・刻印・文字フォント: ○○○○」
     「・シリアル・フォーマット適合度: ○○○○」
     「・金具・ビス・メッキ・研磨処理: ○○○○」
     「・縫製・コバ・素材表面の質感: ○○○○」

4. 『details』（12大超精密チェックリスト）:
   - 12項目について、それぞれpass（true/false）を厳格評価してください。

【出力JSONフォーマット（JSONコードブロックのみ）】
{{
  "detected_model": "ブランド名 正式ライン・製品名 (型番: XXXX / シリアル: XXXX)",
  "overall_score": 98.0,
  "judgment": "基準内",
  "status_code": "PASS",
  "message": "・刻印・文字フォント: ロゴ文字「O」の真円性、PARIS刻印の底面平坦度、フォント間隔が公式基準と完全一致\\n・シリアル・フォーマット適合度: 製造国コードおよび年週打刻のフォント深さとフォーマット完全整合\\n・金具・ビス・メッキ・研磨処理: ジッパー刻印のエッジ面の滑らかな面取り、メッキの密着感良好\\n・縫製・コバ・素材表面の質感: ステッチの斜め傾斜ピッチ、コバ塗料の透明感およびはみ出しなし",
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
        return result_data
    except Exception:
        return fallback_response
