import os
import base64
import json
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic

app = Flask(__name__, static_folder='static')
CORS(app)

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return jsonify({"ok": True, "key": len(key)})

@app.route('/extract', methods=['POST'])
def extract():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return jsonify({"error": "no key"}), 500
    if 'file' not in request.files:
        return jsonify({"error": "no file"}), 400
    f = request.files['file']
    b64 = base64.standard_b64encode(f.read()).decode()
    mt = f.content_type or 'image/jpeg'
    ci = {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}
    if 'pdf' in mt:
        ci = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    client = anthropic.Anthropic(api_key=key)
    msg = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=1024, messages=[{"role": "user", "content": [ci, {"type": "text", "text": "Витягни дані з CMR і поверни JSON: {cmr_number, carrier_name, sender_name, receiver_name, truck_number, trailer_number, loading_country, delivery_country, goods, weight_kg, loading_date}"}]}])
    text = msg.content[0].text.strip().replace('```json','').replace('```','')
    return jsonify(json.loads(text))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
