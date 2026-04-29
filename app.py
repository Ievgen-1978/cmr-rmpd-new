import os
import base64
import json
import traceback
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic

app = Flask(__name__, static_folder='static')
CORS(app)

def load_catalog(filename):
    path = os.path.join(os.path.dirname(__file__), 'data', filename)
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return []

def find_in_catalog(name, catalog):
    if not name:
        return None
    name_upper = name.upper()
    for item in catalog:
        if item['name'].upper() in name_upper or name_upper in item['name'].upper():
            return item
        for alias in item.get('aliases', []):
            if alias.upper() in name_upper or name_upper in alias.upper():
                return item
    return None

def check_vehicle(truck, trailer, vehicles):
    truck_upper = truck.upper() if truck else ''
    trailer_upper = trailer.upper() if trailer else ''
    for v in vehicles:
        if v['truck'].upper() == truck_upper:
            warnings = []
            if v['trailer'].upper() != trailer_upper:
                warnings.append(f"Причеп у каталозі: {v['trailer']}, в CMR: {trailer}")
            return {'found': True, 'gps': v['gps'], 'gps_backup': v['gps_backup'], 'warnings': warnings}
    return {'found': False, 'gps': '', 'gps_backup': '', 'warnings': [f"Авто {truck} не знайдено в каталозі"]}

PROMPT = """Витягни з цього CMR документа наступні дані і поверни ТІЛЬКИ JSON без коментарів:
{
  "cmr_number": "",
  "sender_name": "",
  "sender_address": "",
  "receiver_name": "",
  "receiver_address": "",
  "delivery_place": "",
  "loading_place": "",
  "loading_country": "",
  "delivery_country": "",
  "truck_number": "",
  "trailer_number": "",
  "goods": "",
  "weight_kg": "",
  "quantity": "",
  "loading_date": "",
  "invoice_number": ""
}
Якщо поле не знайдено — залиш порожній рядок. Номери авто завжди великими літерами."""

@app.route('/')
def index():
    return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    return jsonify({"ok": True, "key": len(key)})

@app.route('/extract', methods=['POST'])
def extract():
    try:
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            return jsonify({"error": "API ключ не налаштовано"}), 500
        if 'file' not in request.files:
            return jsonify({"error": "Файл не знайдено"}), 400

        f = request.files['file']
        b64 = base64.standard_b64encode(f.read()).decode()
        mt = f.content_type or 'image/jpeg'
        ci = {"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}
        if 'pdf' in mt:
            ci = {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}

        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1024,
            messages=[{"role": "user", "content": [ci, {"type": "text", "text": PROMPT}]}]
        )
        text = msg.content[0].text.strip().replace('```json','').replace('```','')
        data = json.loads(text)

        # Завантажуємо каталоги
        senders = load_catalog('senders.json')
        receivers = load_catalog('receivers.json')
        vehicles = load_catalog('vehicles.json')
        carrier = load_catalog('carrier.json')

        warnings = []

        # Перевіряємо відправника
        sender_match = find_in_catalog(data.get('sender_name', ''), senders)
        if sender_match:
            data['sender_verified'] = True
            data['sender_canonical'] = sender_match['name']
        else:
            data['sender_verified'] = False
            if data.get('sender_name'):
                warnings.append(f"Відправник '{data['sender_name']}' не знайдений в каталозі")

        # Перевіряємо одержувача
        receiver_match = find_in_catalog(data.get('receiver_name', ''), receivers)
        if receiver_match:
            data['receiver_verified'] = True
            data['receiver_canonical'] = receiver_match['name']
        else:
            data['receiver_verified'] = False
            if data.get('receiver_name'):
                warnings.append(f"Одержувач '{data['receiver_name']}' не знайдений в каталозі")

        # Перевіряємо авто і отримуємо GPS
        vehicle_check = check_vehicle(
            data.get('truck_number', ''),
            data.get('trailer_number', ''),
            vehicles
        )
        data['gps'] = vehicle_check['gps']
        data['gps_backup'] = vehicle_check['gps_backup']
        data['vehicle_verified'] = vehicle_check['found']
        warnings.extend(vehicle_check['warnings'])

        # Додаємо дані перевізника
        if isinstance(carrier, dict):
            data['carrier_name'] = carrier.get('name', '')
            data['carrier_address'] = f"{carrier['address']['street']} {carrier['address']['house']}, {carrier['address']['city']}, {carrier['address']['country']}"
            data['carrier_id'] = carrier.get('identity_number', '')

        data['warnings'] = warnings
        return jsonify(data)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
