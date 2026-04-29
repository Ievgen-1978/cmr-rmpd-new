import os
import base64
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic

app = Flask(__name__, static_folder='static')
CORS(app)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

PROMPT = """Витягни з цього CMR документа наступні дані і поверни ТІЛЬКИ JSON без жодних коментарів, пояснень чи markdown:
{
  "cmr_number": "",
  "carrier_name": "",
  "carrier_address": "",
  "sender_name": "",
  "sender_address": "",
  "receiver_name": "",
  "receiver_address": "",
  "loading_country": "",
  "delivery_country": "",
  "loading_place": "",
  "delivery_place": "",
  "truck_number": "",
  "trailer_number": "",
  "goods": "",
  "weight_kg": "",
  "quantity": "",
  "loading_date": "",
  "cmr_date": ""
}
Якщо поле не знайдено — залиш порожній рядок."""

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/extract', methods=['POST'])
def extract():
    if 'file' not in request.files:
        return jsonify({'error': 'Файл не знайдено'}), 400

    file = request.files['file']
    file_bytes = file.read()
    b64 = base64.standard_b64encode(file_bytes).decode('utf-8')
    media_type = file.content_type or 'image/jpeg'

    if media_type == 'application/pdf':
        content_item = {
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf", "data": b64}
        }
    else:
        content_item = {
            "type": "image",
            "source": {"type": "base64", "media_type": media_type, "data": b64}
        }

    message = client.messages.create(
        model="claude-opus-4-5",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": [content_item, {"type": "text", "text": PROMPT}]
        }]
    )

    text = message.content[0].text.strip()
    text = text.replace('```json', '').replace('```', '').strip()
    data = json.loads(text)
    return jsonify(data)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
