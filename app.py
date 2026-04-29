import os
import base64
import json
import traceback
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic

app = Flask(__name__, static_folder='static')
CORS(app)

PROMPT = """Витягни з цього CMR документа наступні дані і поверни ТІЛЬКИ JSON без жодних коментарів, пояснень чи markdown:
{"cmr_number":"","carrier_name":"","carrier_address":"","sender_name":"","sender_address":"","receiver_name":"","receiver_address":"","loading_country":"","delivery_country":"","loading_place":"","delivery_place":"","truck_number":"","trailer_number":"","goods":"","weight_kg":"","quantity":"","loading_date":"","cmr_date":""}
Якщо поле не знайдено — залиш порожній рядок."""

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    return jsonify({"status": "ok", "api_key_set": bool(api_key), "api_key_len": len(api_key)})

@app.route('/extract', methods=['POST'])
def extract():
    try:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key:
            return jsonify({'error': 'ANTHROPIC_API_KEY не встановлено'}), 500

        if 'file' not in request.files:
            return jsonify({'error': 'Файл не знайдено'}), 400

        file = request.files['file']
        file_bytes = file.read()
        b64 = base64.standard_b64encode(file_bytes).decode('utf-8')
        media_type = file.content_type or 'image/jpeg'

        if 'pdf' in media_type:
            content_item = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
        else:
            content_item = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}

        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": [content_item, {"type": "text", "text": PROMPT}]}]
        )

        text = message.content[0].text.strip().replace('```json','').replace('```','').strip()
        data = json.loads(text)
        return jsonify(data)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)
