import os
import base64
import json
import traceback
import io
import fitz  # PyMuPDF
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic
from PIL import Image

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
    # Точне співпадіння
    for v in vehicles:
        if v['truck'].upper().replace(' ', '') == truck_upper:
            return v.get('gps', ''), v.get('gps_backup', '')
    # Нечітке: починається з розпізнаного номера або навпаки
    for v in vehicles:
        catalog_truck = v['truck'].upper().replace(' ', '')
        if catalog_truck.startswith(truck_upper) or truck_upper.startswith(catalog_truck[:6]):
            return v.get('gps', ''), v.get('gps_backup', '')
    return '', ''

def compress_image(file_bytes, max_bytes=4*1024*1024):
    img = Image.open(io.BytesIO(file_bytes))
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')
    quality = 85
    while quality >= 40:
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality)
        if buf.tell() <= max_bytes:
            return buf.getvalue(), 'image/jpeg'
        quality -= 10
    img.thumbnail((2000, 2000), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=70)
    return buf.getvalue(), 'image/jpeg'

def compress_pdf_page(pix, max_bytes=4*1024*1024):
    img_bytes = pix.tobytes("jpeg")
    if len(img_bytes) <= max_bytes:
        return img_bytes
    img = Image.open(io.BytesIO(img_bytes))
    quality = 75
    while quality >= 40:
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=quality)
        if buf.tell() <= max_bytes:
            return buf.getvalue()
        quality -= 10
    img.thumbnail((2000, 2000), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=60)
    return buf.getvalue()

PROMPT = """Це міжнародна товарно-транспортна накладна CMR. Витягни дані і поверни ТІЛЬКИ JSON без коментарів і без markdown.

СТРУКТУРА ПОЛІВ CMR — читай ТІЛЬКИ вказані поля:

Поле 1 (лівий верх) = ВІДПРАВНИК: назва компанії + адреса + країна
Поле 2 (під полем 1) = ОДЕРЖУВАЧ: тільки НАЗВА компанії. Адресу одержувача НЕ брати з цього поля!
Поле 3 (під полем 2) = АДРЕСА ДОСТАВКИ: точна адреса складу куди везуть вантаж (вулиця, місто, індекс, країна)
Поле 4 = МІСЦЕ ЗАВАНТАЖЕННЯ: місто і країна звідки забрали вантаж (НЕ адреса одержувача!)
Поле 7 = КІЛЬКІСТЬ МІСЦЬ (число палет, коробок тощо)
Поле 9 = НАЙМЕНУВАННЯ ВАНТАЖУ
Поле 11 = ВАГА БРУТТО в кг
Поле 16 (правий верх, печатка) = ПЕРЕВІЗНИК — завжди TZOV SMART TRANS HRUP
Поле 17 або 22 (внизу де підпис перевізника) = НОМЕРИ АВТО І ПРИЧЕПА — читай ПОВНІСТЮ всі літери і цифри
Поле 21 = ДАТА складання CMR

КРИТИЧНІ ПРАВИЛА:
1. receiver_address — брати ТІЛЬКИ з поля 3, це адреса складу призначення. НЕ з поля 2.
2. receiver_name — брати тільки назву з поля 2.
3. loading_place — місто звідки забрали вантаж (поле 4), НЕ адреса одержувача.
4. Номери авто — читай ПОВНІСТЮ: всі літери і цифри. Наприклад AC1566EO, не AC1566. Великими літерами без пробілів.
5. Якщо авто і причеп через "/" — формат АВТО/ПРИЧЕП.
6. Умови оплати (DAP, FOB, EXW, FCA) — НЕ є місцем. Ігноруй.
7. Кількість — число з одиницею (наприклад: "51 палета").
8. Дата CMR — з поля 21.

JSON що треба повернути:
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
  "volume_m3": "",
  "quantity": "",
  "loading_date": "",
  "cmr_date": "",
  "invoice_number": "",
  "payment_terms": ""
}

Якщо поле не знайдено — порожній рядок."""

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
        file_bytes = f.read()
        mt = f.content_type or 'image/jpeg'

        if 'pdf' in mt:
            if len(file_bytes) > 4 * 1024 * 1024:
                doc = fitz.open(stream=file_bytes, filetype="pdf")
                mat = fitz.Matrix(2, 2)
                content_items = []
                for page in doc:
                    pix = page.get_pixmap(matrix=mat)
                    img_bytes = compress_pdf_page(pix)
                    b64 = base64.standard_b64encode(img_bytes).decode()
                    content_items.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
                doc.close()
            else:
                content_items = [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.standard_b64encode(file_bytes).decode()}}]
        else:
            if len(file_bytes) > 4 * 1024 * 1024:
                file_bytes, mt = compress_image(file_bytes)
            b64 = base64.standard_b64encode(file_bytes).decode()
            content_items = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": b64}}]

        client = anthropic.Anthropic(api_key=key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": content_items + [{"type": "text", "text": PROMPT}]}]
        )
        text = msg.content[0].text.strip().replace('```json','').replace('```','')
        data = json.loads(text)

        senders = load_catalog('senders.json')
        receivers = load_catalog('receivers.json')
        vehicles = load_catalog('vehicles.json')
        carrier = load_catalog('carrier.json')
        warnings = []

        if isinstance(carrier, dict):
            addr = carrier.get('address', {})
            data['carrier_name'] = carrier.get('name', '')
            data['carrier_address'] = f"{addr.get('street','')} {addr.get('house','')}, {addr.get('city','')}, {addr.get('country','')}, {addr.get('postal_code','')}"
            data['carrier_id'] = carrier.get('identity_number', '')

        truck = data.get('truck_number', '').replace(' ', '')
        gps, gps_backup = get_vehicle_gps(truck, vehicles)
        data['gps'] = gps
        data['gps_backup'] = gps_backup
        data['vehicle_verified'] = bool(gps)
        if truck and not gps:
            warnings.append(f"Авто {truck} не знайдено в каталозі — GPS невідомий")

        sender_match = find_in_catalog(data.get('sender_name', ''), senders)
        data['sender_verified'] = bool(sender_match)
        if sender_match:
            data['sender_canonical'] = sender_match['name']
        elif data.get('sender_name'):
            warnings.append(f"Відправник '{data['sender_name']}' — новий, немає в каталозі")

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
        senders.append({"name": body.get('name',''), "aliases": body.get('aliases',[]), "address": body.get('address',{})})
        return jsonify({"ok": save_catalog('senders.json', senders), "message": "Відправника додано"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/add-receiver', methods=['POST'])
def add_receiver():
    try:
        body = request.get_json()
        receivers = load_catalog('receivers.json')
        receivers.append({"name": body.get('name',''), "aliases": body.get('aliases',[]), "address": body.get('address',{})})
        return jsonify({"ok": save_catalog('receivers.json', receivers), "message": "Одержувача додано"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/add-vehicle', methods=['POST'])
def add_vehicle():
    try:
        body = request.get_json()
        vehicles = load_catalog('vehicles.json')
        vehicles.append({
            "truck": body.get('truck','').upper().replace(' ',''),
            "trailer": body.get('trailer','').upper().replace(' ',''),
            "gps": body.get('gps',''),
            "gps_backup": body.get('gps_backup','')
        })
        return jsonify({"ok": save_catalog('vehicles.json', vehicles), "message": "Авто додано"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
