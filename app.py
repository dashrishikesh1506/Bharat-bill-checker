from flask import Flask, request, jsonify, send_from_directory
import os
import io
import json
import base64
from dotenv import load_dotenv
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Load environment variables from .env
load_dotenv()

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 15 * 1024 * 1024
limiter = Limiter(get_remote_address, app=app, default_limits=["100 per hour"])

@app.errorhandler(429)
def rate_limit_error(error):
    return jsonify({"error": "Too many requests. Please wait and try again later."}), 429

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

def clean_json_response(raw_text):
    """Safely extracts JSON from model response even if surrounded by markdown code blocks."""
    raw = raw_text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        # Remove first line if it's ``` or ```json
        if lines[0].startswith("```"):
            lines = lines[1:]
        # Remove last line if it's ```
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    elif "{" in raw and "}" in raw:
        # Find the first { and last }
        start = raw.find("{")
        end = raw.rfind("}") + 1
        raw = raw[start:end]
    return json.loads(raw)

def get_file_info(file, filename):
    ext = filename.lower().split('.')[-1]
    file_bytes = file.read()
    
    mime_map = {
        'pdf': 'application/pdf',
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'webp': 'image/webp'
    }
    mime_type = mime_map.get(ext)
    if not mime_type:
        return {"error": f"Unsupported file type .{ext}. Please upload a PDF, JPG, PNG, or WEBP file."}
    
    return {
        "bytes": file_bytes,
        "mime": mime_type,
        "ext": ext,
        "filename": filename
    }

def call_ai(prompt, files=None, response_json=False):
    """
    Calls Google Gemini (preferred free API) or Anthropic Claude based on configured keys.
    """
    load_dotenv(override=True)
    gemini_key = os.environ.get("GEMINI_API_KEY", "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()

    if gemini_key:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=gemini_key)
        contents = []

        if files:
            for f in files:
                part = types.Part.from_bytes(data=f["bytes"], mime_type=f["mime"])
                contents.append(part)

        contents.append(prompt)

        config_params = {}
        if response_json:
            config_params["response_mime_type"] = "application/json"

        config = types.GenerateContentConfig(**config_params) if config_params else None

        # Try active Gemini models
        models_to_try = [
            "gemini-3.5-flash-lite",
            "gemini-3.1-flash-lite",
            "gemini-3-flash-preview",
            "gemini-3.8-flash",
            "gemini-flash-latest"
        ]
        last_error = None

        for model_name in models_to_try:
            try:
                response = client.models.generate_content(
                    model=model_name,
                    contents=contents,
                    config=config
                )
                return response.text
            except Exception as e:
                last_error = e
                # If model is not found, try next model; otherwise raise
                continue

        raise last_error

    elif anthropic_key:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_key)

        messages_content = []
        if files:
            for f in files:
                if f["mime"] == "application/pdf":
                    # For Anthropic document support
                    b64 = base64.standard_b64encode(f["bytes"]).decode('utf-8')
                    messages_content.append({
                        "type": "document",
                        "source": {
                            "type": "base64",
                            "media_type": "application/pdf",
                            "data": b64
                        }
                    })
                else:
                    b64 = base64.standard_b64encode(f["bytes"]).decode('utf-8')
                    messages_content.append({
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": f["mime"],
                            "data": b64
                        }
                    })

        messages_content.append({
            "type": "text",
            "text": prompt
        })

        # Try sonnet 3.5, fallback to haiku
        anthropic_models = ["claude-3-5-sonnet-20241022", "claude-3-haiku-20240307"]
        last_error = None
        for model in anthropic_models:
            try:
                message = client.messages.create(
                    model=model,
                    max_tokens=2000,
                    messages=[{"role": "user", "content": messages_content}]
                )
                return message.content[0].text
            except Exception as e:
                last_error = e
                continue

        raise last_error
    else:
        raise ValueError(
            "No AI API key found! Please get a FREE Gemini API key from https://aistudio.google.com/ "
            "and add GEMINI_API_KEY=your_key to your .env file."
        )

@app.route('/')
def home():
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), 'index.html')

@app.route('/health', methods=['GET'])
def health():
    load_dotenv(override=True)
    gemini_key = bool(os.environ.get("GEMINI_API_KEY", "").strip())
    anthropic_key = bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
    return jsonify({
        "status": "running",
        "gemini_configured": gemini_key,
        "anthropic_configured": anthropic_key,
        "active_provider": "Gemini (Free)" if gemini_key else ("Anthropic" if anthropic_key else "None configured")
    })

@app.route('/analyze', methods=['POST'])
@limiter.limit('10 per hour')
def analyze_bill():
    try:
        if 'bill' not in request.files:
            return jsonify({'error': 'No bill file uploaded'}), 400

        file = request.files['bill']
        if not file.filename:
            return jsonify({'error': 'Empty file selected'}), 400

        bill_type = request.form.get('bill_type', 'electricity')
        language = request.form.get('language', 'english')

        file_info = get_file_info(file, file.filename)
        if "error" in file_info:
            return jsonify({'error': file_info["error"]}), 400

        lang_instruction = "Respond in Hindi language." if language == 'hindi' else "Respond in English."

        prompt = f"""
You are an expert at analyzing Indian utility bills ({bill_type} bill).
{lang_instruction}

Analyze this utility bill carefully. Calculate and check all charges, units consumed, rates, taxes, and fees.
Identify any possible overcharges, incorrect meter calculations, or suspicious hidden fees.

Return ONLY a valid JSON object matching this exact structure, with no markdown code blocks or surrounding text:
{{
    "bill_type": "{bill_type}",
    "customer_name": "name from bill or Unknown",
    "billing_period": "period from bill (e.g., Oct 2026)",
    "total_amount": "total amount as a clean number only (e.g. 1450)",
    "breakdown": [
        {{
            "item": "charge name (e.g. Energy Charges, Fixed Charges, Fuel Surcharge, Electricity Duty)",
            "amount": "₹ amount or clean number",
            "status": "ok or suspicious or overcharged",
            "explanation": "clear 1-sentence plain explanation of what this charge means"
        }}
    ],
    "overcharge_amount": "suspected overcharge amount as number only, or 0 if none",
    "trust_score": 85,
    "summary": "2-3 sentence plain language summary of the bill status and health",
    "red_flags": ["list of issues, anomalies, or empty list if bill looks fair"]
}}
"""

        raw_response = call_ai(prompt, files=[file_info], response_json=True)
        result = clean_json_response(raw_response)
        return jsonify(result)

    except Exception as e:
        error_msg = str(e)
        if "credit balance is too low" in error_msg.lower():
            error_msg = "Anthropic Claude API credits ran out. Please set GEMINI_API_KEY in .env to use the FREE Google Gemini API instead!"
        return jsonify({'error': error_msg}), 500


@app.route('/chat', methods=['POST'])
@limiter.limit('30 per hour')
def chat_about_bill():
    try:
        data = request.json or {}
        question = data.get('question', '').strip()
        bill_context = data.get('bill_context', '')
        language = data.get('language', 'english')

        if not question:
            return jsonify({'error': 'No question provided'}), 400

        lang_instruction = "Respond in Hindi." if language == 'hindi' else "Respond in English."

        prompt = f"""
You are a helpful Indian utility bill expert.
{lang_instruction}

Bill data context:
{bill_context}

User question:
{question}

Answer simply and helpfully in 2-3 sentences. If the bill data does not contain the answer, say so honestly.
"""

        raw_response = call_ai(prompt, response_json=False)
        return jsonify({"answer": raw_response.strip()})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/compare', methods=['POST'])
@limiter.limit('10 per hour')
def compare_bills():
    try:
        if 'bill1' not in request.files or 'bill2' not in request.files:
            return jsonify({'error': 'Please upload two bills to compare'}), 400

        file1 = request.files['bill1']
        file2 = request.files['bill2']
        bill_type = request.form.get('bill_type', 'electricity')
        language = request.form.get('language', 'english')

        file_info1 = get_file_info(file1, file1.filename)
        if "error" in file_info1:
            return jsonify({'error': f"Bill 1 error: {file_info1['error']}"}), 400

        file_info2 = get_file_info(file2, file2.filename)
        if "error" in file_info2:
            return jsonify({'error': f"Bill 2 error: {file_info2['error']}"}), 400

        lang_instruction = "Respond in Hindi." if language == 'hindi' else "Respond in English."

        prompt = f"""
You are an expert at analyzing and comparing Indian utility bills ({bill_type}).
{lang_instruction}

Compare these two bills (Bill 1 is the older bill, Bill 2 is the more recent bill).
Analyze the difference in total charges, units consumed, and explain why the bill increased or decreased.

Return ONLY a valid JSON object matching this exact structure:
{{
    "bill1": {{
        "period": "billing period for bill 1",
        "total": "total amount as number",
        "units": "units consumed if available, or N/A"
    }},
    "bill2": {{
        "period": "billing period for bill 2",
        "total": "total amount as number",
        "units": "units consumed if available, or N/A"
    }},
    "difference": "difference as clean number (bill2 minus bill1)",
    "percentage_change": "percentage change as clean number",
    "reason": "likely reason for change in 2 sentences (e.g., seasonal AC usage, tariff hike)",
    "advice": "one actionable tip to reduce this bill"
}}
"""

        raw_response = call_ai(prompt, files=[file_info1, file_info2], response_json=True)
        result = clean_json_response(raw_response)
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    print("Bharat Bill Checker Backend starting on http://127.0.0.1:5000 ...")
    app.run(debug=True, port=5000)