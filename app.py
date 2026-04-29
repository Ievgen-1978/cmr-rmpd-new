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

def save_catalog(filename, data):
    path = os.path.join(os.path.dirname(__file__), 'data', filename)
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except:
        return False

def find_in_catalog(name, catalog):
    if not name:
        return None
    name_upper = name.upper().strip()
    for item in catalog:
        if item['name'].upper() in name_upper or name_upper in item['name'].upper():
            return item
        for alias in item.get('aliases', []):
            if alias.upper() in name_upper or name_upper in alias.upper():
                return item
    return None

def get_vehicle_gps(truck, vehicles):
    if not truck:
        return '', ''
    truck_upper = truck.upper().replace(' ', '')
    for v in vehicles:
        if v['truck'].upper().replace(' ', '') == truck_upper:
            return v.get('gps', ''), v.get('gps_backup', '')
    return '', ''

PROMPT = """Це міжнародна товарно-транспортна накладна (CMR). Витягни дані і поверни ТІЛЬКИ JSON:

ВАЖЛИВО:
- Поле 1 = ВІДПРАВНИК (хто відправляє вантаж, зазвичай в Україні)
- Поле 2 = ОДЕРЖУВАЧ (хто отримує вантаж, зазвичай за кордоном)
- Поле 3 = МІСЦЕ ДОСТАВКИ (місто/адреса де розвантажують)
- Поле 4 = МІСЦЕ ЗАВАНТАЖЕННЯ (де і коли забрали вантаж)
- Поле 16 = ПЕРЕВІЗНИК
- Поле 9 = НАЙМЕНУВАННЯ ВАНТАЖУ
- Поле 11 = ВАГА БРУТТО (кг)
- Умови оплати (DAP, FOB, EXW тощо) НЕ є місцем доставки

{
  "cmr_number": "",
  "sender_name": "",
  "sender_address": "",
  "receiver_name": "",
  "receiver_address": "",
  "loading_place": "",
  "loading_country": "",
  "delivery_place": "",
  "delivery_country": "",
  "truck_number": "",
  "trailer_number": "",
  "goods": "",
  "goods_code": "",
  "weight_kg": "",
  "quantity": "",
  "loading_date": "",
  "invoice_number": "",
  "payment_terms": ""
}

Номери авто — великими літерами без пробілів. Якщо поле не знайдено — порожній рядок."""

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
            max_tokens=1500,
            messages=[{"role": "user", "content": [ci, {"type": "text", "text": PROMPT}]}]
        )
        text = msg.content[0].text.strip().replace('```json','').replace('```','')
        data = json.loads(text)

        senders = load_catalog('senders.json')
        receivers = load_catalog('receivers.json')
        vehicles = load_catalog('vehicles.json')
        carrier = load_catalog('carrier.json')
        warnings = []

        # Перевізник з каталогу
        if isinstance(carrier, dict):
            data['carrier_name'] = carrier.get('name', '')
            addr = carrier.get('address', {})
            data['carrier_address'] = f"{addr.get('street','')} {addr.get('house','')}, {addr.get('city','')}, {addr.get('country','')}, {addr.get('postal_code','')}"
            data['carrier_id'] = carrier.get('identity_number', '')

        # GPS з каталогу авто
        truck = data.get('truck_number', '').replace(' ', '')
        gps, gps_backup = get_vehicle_gps(truck, vehicles)
        data['gps'] = gps
        data['gps_backup'] = gps_backup
        if truck and not gps:
            warnings.append(f"Авто {truck} не знайдено в каталозі — GPS невідомий")
            data['vehicle_verified'] = False
        else:
            data['vehicle_verified'] = bool(gps)

        # Відправник
        sender_match = find_in_catalog(data.get('sender_name', ''), senders)
        data['sender_verified'] = bool(sender_match)
        if sender_match:
            data['sender_canonical'] = sender_match['name']
        elif data.get('sender_name'):
            warnings.append(f"Відправник '{data['sender_name']}' — новий, немає в каталозі")

        # Одержувач
        receiver_match = find_in_catalog(data.get('receiver_name', ''), receivers)
        data['receiver_verified'] = bool(receiver_match)
        if receiver_match:
            data['receiver_canonical'] = receiver_match['name']
        elif data.get('receiver_name'):
            warnings.append(f"Одержувач '{data['receiver_name']}' — новий, немає в каталозі")

        data['warnings'] = warnings
        return jsonify(data)

    except Exception as e:
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/add-sender', methods=['POST'])
def add_sender():
    try:
        body = request.get_json()
        senders = load_catalog('senders.json')
        new_entry = {
            "name": body.get('name', ''),
            "aliases": body.get('aliases', []),
            "address": body.get('address', {})
        }
        senders.append(new_entry)
        if save_catalog('senders.json', senders):
            return jsonify({"ok": True, "message": "Відправника додано"})
        return jsonify({"ok": False, "message": "Помилка збереження"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/add-receiver', methods=['POST'])
def add_receiver():
    try:
        body = request.get_json()
        receivers = load_catalog('receivers.json')
        new_entry = {
            "name": body.get('name', ''),
            "aliases": body.get('aliases', []),
            "address": body.get('address', {})
        }
        receivers.append(new_entry)
        if save_catalog('receivers.json', receivers):
            return jsonify({"ok": True, "message": "Одержувача додано"})
        return jsonify({"ok": False, "message": "Помилка збереження"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/add-vehicle', methods=['POST'])
def add_vehicle():
    try:
        body = request.get_json()
        vehicles = load_catalog('vehicles.json')
        new_entry = {
            "truck": body.get('truck', '').upper().replace(' ', ''),
            "trailer": body.get('trailer', '').upper().replace(' ', ''),
            "gps": body.get('gps', ''),
            "gps_backup": body.get('gps_backup', '')
        }
        vehicles.append(new_entry)
        if save_catalog('vehicles.json', vehicles):
            return jsonify({"ok": True, "message": "Авто додано"})
        return jsonify({"ok": False, "message": "Помилка збереження"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
