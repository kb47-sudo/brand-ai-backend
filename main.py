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

app = FastAPI(title="Multi-AI Fallback Engine", version="109.0")

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
        "engine": "Multi-AI Fallback Engine v109.0",
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
        print(f"HTTP Post Error ({url}): {e}")
    return None

def execute_multi_ai_analysis(prompt: str, pil_images: list, base64_images: list):
    # --- フェーズ 1: Gemini API ---
    if GEMINI_API_KEY:
        try:
            genai.configure(api_key=GEMINI_API_KEY)
            generation_config = {
                "temperature": 0.2,
                "response_mime_type": "application/json",
            }
            for g_model in ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-1.5-pro"]:
                try:
                    model = genai.GenerativeModel(model_name=g_model, generation_config=generation_config)
                    res = model.generate_content([prompt] + pil_images)
                    if res and hasattr(res, 'text') and res.text:
                        return res.text.strip(), None
                except Exception as g_err:
                    print(f"Gemini ({g_model}) Skip: {g_err}")
        except Exception as e:
            print(f"Gemini Core Error: {e}")

    # --- フェーズ 2: OpenRouter API ---
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

    # --- フェーズ 3: Groq API ---
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

    return None, "AI連携処理でエラーが発生しました。"

def process_authentication_job(job_id: str, brand: str, category: str, model_number: str, raw_bytes_list: list, base64_images: list, pil_images: list):
    user_hint = f"ユーザー手入力型番: {model_number}" if model_number else "ユーザー手入力型番: なし（画像から品名・型番を完全自動判別すること）"

    prompt = f"""
あなたは日本のコメ兵・大黒屋・銀座ラシン等のプロ鑑定士および買取相場アナリストです。
送信された部位写真群（最大5枚）を画像から直接解析し、品物を特定した上で、リアルな真贋一致率スコア（0〜100%）と、その特定された品
