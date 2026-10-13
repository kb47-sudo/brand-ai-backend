import os
import io
import json
import re
import uuid
import time
import requests
import base64
from PIL import Image, ImageEnhance
from fastapi import FastAPI, Form, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
import google.generativeai as genai

app = FastAPI(title="Multi-AI Fallback Authenticator Engine", version="105.0")

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
        "engine": "Multi-AI Fallback Authenticator v105.0",
        "gemini_active": bool(GEMINI_API_KEY),
        "openrouter_active": bool(OPENROUTER_API_KEY),
        "groq_active": bool(GROQ_API_KEY)
    }

def clean_old_jobs():
    now = time.time()
    expired_keys = [k for k, v in JOBS.items() if now - v.get("created_at", now) > 600]
    for k in expired_keys:
        del JOBS[k]

def execute_multi_ai_analysis(prompt: str, pil_images: list, base64_images: list):
    # --- 第1フェーズ: Gemini API (実稼働モデル順次試行) ---
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        generation_config = {
            "temperature": 0.2,
            "response_mime_type": "application/json",
        }
        # 404が出ない実稼働モデルのリスト
        gemini_candidate_models = [
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-2.0-flash-exp"
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
            except Exception as e:
                print(f"Gemini Model {g_model} Error: {e}")

    # --- 第2フェーズ: OpenRouter API (Gemini制限時・エラー時の自動切替) ---
    if OPENROUTER_API_KEY and base64_images:
        openrouter_models = [
            "google/gemini-2.0-flash-exp:free",
            "meta-llama/llama-3.2-11b-vision-instruct:free",
            "qwen/qwen-2-vl-72b-instruct:free"
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
                res = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=or_payload, timeout=15)
                if res.status_code == 200:
                    res_json = res.json()
                    if "choices" in res_json and len(res_json["choices"]) > 0:
                        content = res_json["choices"][0]["message"]["content"]
                        if content and len(content.strip()) > 0:
                            return content.strip(), None
            except Exception as e:
                print(f"OpenRouter Model {or_model} Error: {e}")

    # --- 第3フェーズ: Groq API ---
    if GROQ_API_KEY and base64_images:
        try:
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
                "model": "llama-3.2-11b
