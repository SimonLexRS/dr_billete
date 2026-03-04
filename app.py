"""
Dr. Billetes - Detector de Billetes Ilegales BCB Bolivia
Servidor Flask principal.
"""

import json
import os
import queue
import shutil
import threading

from flask import Flask, render_template, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from services.detector_service import DetectorService
import config


def ensure_data_files():
    """Copy bundled data files to DATA_DIR if they don't exist yet."""
    bundled = os.path.join(os.path.dirname(__file__), "data")
    for fn in ("bcb_series.json", "model_weights.json"):
        dest = os.path.join(config.DATA_DIR, fn)
        if not os.path.exists(dest):
            src = os.path.join(bundled, fn)
            if os.path.exists(src):
                os.makedirs(config.DATA_DIR, exist_ok=True)
                shutil.copy2(src, dest)


ensure_data_files()

app = Flask(__name__)
CORS(app)

detector = DetectorService()


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/scan", methods=["POST"])
def scan_banknote():
    """Escanea una imagen de billete con OCR y verifica.
    Retorna SSE con pings cada 10s para evitar timeout en conexiones moviles."""
    data = request.get_json()
    if not data or "image" not in data:
        return jsonify({"success": False, "message": "No se envio imagen."}), 400

    image_b64 = data["image"]
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    result_queue = queue.Queue()

    def do_scan():
        try:
            result = detector.scan_image(image_b64)
            result_queue.put(result)
        except Exception as e:
            result_queue.put({"success": False, "message": str(e)})

    threading.Thread(target=do_scan, daemon=True).start()

    def generate():
        while True:
            try:
                result = result_queue.get(timeout=10)
                yield f"data: {json.dumps(result)}\n\n"
                break
            except queue.Empty:
                yield ": ping\n\n"  # keepalive — previene timeout de proxy/movil

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/verify", methods=["POST"])
def verify_serial():
    """Verifica un numero de serie manualmente."""
    data = request.get_json()
    if not data:
        return jsonify({"success": False, "message": "Datos invalidos."}), 400

    denomination = data.get("denomination")
    serial = data.get("serial")

    if not denomination or not serial:
        return jsonify({
            "success": False,
            "message": "Se requiere denominacion y numero de serie.",
        }), 400

    try:
        denomination = int(denomination)
        serial = int(str(serial).replace(" ", "").replace("-", ""))
    except (ValueError, TypeError):
        return jsonify({
            "success": False,
            "message": "La denominacion y serial deben ser numeros validos.",
        }), 400

    result = detector.verify_serial(denomination, serial)
    return jsonify(result)


@app.route("/api/train", methods=["POST"])
def train_model():
    """Entrena la red neuronal."""
    data = request.get_json() or {}
    epochs = data.get("epochs", 100)
    learning_rate = data.get("learning_rate", 0.05)
    samples = data.get("samples", 8000)

    try:
        result = detector.train_model(
            epochs=int(epochs),
            learning_rate=float(learning_rate),
            samples=int(samples),
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500


@app.route("/api/stats")
def get_stats():
    """Retorna estadisticas del sistema."""
    return jsonify(detector.get_stats())


@app.route("/api/ranges")
def get_ranges():
    """Retorna los rangos ilegales del BCB."""
    return jsonify(detector.get_ranges())


@app.route("/api/history")
def get_history():
    """Retorna historial de escaneos paginado."""
    page = request.args.get("page", 1, type=int)
    per_page = min(request.args.get("per_page", 20, type=int), 100)
    verdict = request.args.get("verdict", None)
    denomination = request.args.get("denomination", None)
    return jsonify(detector.get_history(
        page=page,
        per_page=per_page,
        verdict_filter=verdict,
        denomination_filter=denomination,
    ))


@app.route("/api/stats/chart")
def get_chart_data():
    """Retorna datos agregados por dia para graficas."""
    days = request.args.get("days", 30, type=int)
    return jsonify(detector.get_chart_data(min(days, 90)))


@app.route("/api/test-connection")
def test_connection():
    """Prueba la conexion con DeepSeek."""
    return jsonify(detector.test_api())


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  Dr. Billetes - Detector de Billetes Ilegales BCB")
    print("  Comunicado CP9/2026 - Serie B")
    print(f"  Servidor: http://localhost:{config.FLASK_PORT}")
    print("=" * 60 + "\n")
    app.run(
        host=config.FLASK_HOST,
        port=config.FLASK_PORT,
        debug=config.FLASK_DEBUG,
    )
