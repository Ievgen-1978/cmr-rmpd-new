import os
import base64
import json
import traceback
import io
import fitz
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
                cat_name = item['name'].upper()
        if cat_name in name_upper or name_upper in cat_name:
                        return item
                    for alias in item.get('aliases', []):
                                    if alias.upper() in name_upper or name_upper in alias.upper():
                                                        return item
                                            name_words = set(w for w in name_upper.split() if len(w) > 3)
    for item in catalog:
                cat_words = set(w for w in item['name'].upper().split() if len(w) > 3)
        if len(name_words & cat_words) >= 2:
                        return item
        for alias in item.get('aliases', []):
                        alias_words = set(w for w in alias.upper().split() if len(w) > 3)
            if len(name_words & alias_words) >= 2:
                                return item
    return None

def get_address_from_catalog(item):
        if not item:
                    return ''
    addr = item.get('address', {})
    if isinstance(addr, dict):
                parts = [addr.get('street',''), addr.get('city',''), addr.get('country',''), addr.get('postal_code','')]
        return ', '.join(p for p in parts if p)
    return str(addr)

def get_vehicle_gps(truck, vehicles):
        if not truck:
                    return '', ''
    truck_upper = truck.upper().replace(' ', '')
    for v in vehicles:
                if v['truck'].upper().replace(' ', '') == truck_upper:
                                return v.get('gps', ''), v.get('gps_backup', '')
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

PROMPT = """This is an international consignment note CMR. Extract data and return ONLY JSON without comments or markdown.

CMR FIELD STRUCTURE:

Field 1 (top left) = SENDER: company name + address + country
Field 2 (below field 1, LEFT side) = CONSIGNEE/RECEIVER: company name + legal address + country
Field 3 (below field 2) = DELIVERY PLACE: actual warehouse address where goods are delivered
Field 4 = LOADING PLACE AND DATE: city, country, loading date
Field 16 (RIGHT side with stamp) = CARRIER = always TZOV SMART TRANS HRUP. NOT the receiver!
Field 17 or 22/26 (bottom where carrier signs) = TRUCK AND TRAILER NUMBERS
Field 21 = CMR DATE

CRITICAL RULES:
1. sender_name, sender_address - ONLY from field 1 (top left)
2. receiver_name - ONLY the company name from field 2 (LEFT side, below sender)
3. receiver_address - legal address from field 2 (LEFT side)
4. WARNING: Field 16 (RIGHT side with stamp) = CARRIER = TZOV SMART TRANS HRUP. NEVER use field 16 as receiver!
5. delivery_place - address from field 3 (actual delivery warehouse)
6. loading_place - city from field 4. NOT the carrier address from field 16!
7. loading_date - date from field 4
8. cmr_date - date from field 21
9. delivery_country - country of receiver from field 2 or delivery place from field 3. NOT carrier country!
10. Truck numbers - FULL uppercase without spaces (AC1566EO not AC1566)
11. transport_type:
    - Poland is loading OR delivery country -> "Transport dwustronny"
    - Poland is NOT involved (UA->CH, UA->DE, UA->UK etc) -> "Transport tranzytowy"
12. border_crossing - empty string
13. end_date - empty string if not in document

JSON:
{
  "cmr_number": "",
    "truck_number": "",
      "trailer_number": "",
        "loading_date": "",
          "end_date": "",
            "loading_country": "",
              "delivery_country": "",
                "transport_type": "",
                  "cmr_date": "",
                    "loading_place": "",
                      "delivery_place": "",
                        "border_crossing": "",
                          "sender_name": "",
                            "sender_address": "",
                              "receiver_name": "",
                                "receiver_address": ""
}

If field not found - empty string."""

@app.route('/')
def index():
        return send_from_directory('static', 'index.html')

@app.route('/health')
def health():
        key = os.environ.get("ANTHROPIC_API_KEY", "")
    return jsonify({"ok": True, "key": len(key)})

@app.route('/border-crossings')
def border_crossings():
        data = load_catalog('border_crossings.json')
    return jsonify(data)

@app.route('/extract', methods=['POST'])
def extract():
        try:
                    key = os.environ.get("ANTHROPIC_API_KEY", "")
                    if not key:
                                    return jsonify({"error": "API key not configured"}), 500
                                if 'file' not in request.files:
                                                return jsonify({"error": "File not found"}), 400

                    f = request.files['file']
                    file_bytes = f.read()
                    mt = f.content_type or 'image/jpeg'

            if 'pdf' in mt:
                            if len(file_bytes) > 4 * 1024 * 1024:
                                                doc = fitz.open(stream=f
