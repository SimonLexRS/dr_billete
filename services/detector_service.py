"""
Servicio Detector: orquesta OCR + Base de datos BCB + Red Neuronal
para generar un veredicto completo sobre un billete.
"""

import base64
import json
import os
import threading
import uuid
from datetime import datetime

from models.bcb_database import BCBDatabase
from models.neural_network import NeuralNetwork
from services.ocr_service import OCRService
from services.database_service import DatabaseService
from services.bill_detector_service import BillDetectorService
import config


class DetectorService:
    def __init__(self):
        self.db = BCBDatabase()
        self.nn = NeuralNetwork()
        self.ocr = OCRService()
        self.database = DatabaseService()
        self.bill_detector = BillDetectorService()
        self.stats_path = config.SCAN_STATS_PATH
        self.scan_stats = self._load_stats()

        # Intentar cargar pesos pre-entrenados
        if self.nn.load_weights(config.MODEL_WEIGHTS_PATH):
            print("[DetectorService] Modelo neuronal cargado desde disco.")
        else:
            print("[DetectorService] No hay modelo pre-entrenado. Entrene desde el dashboard.")

    def _load_stats(self) -> dict:
        default = {"total_scans": 0, "illegal_count": 0, "legal_count": 0}
        if os.path.exists(self.stats_path):
            try:
                with open(self.stats_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                for key in default:
                    if key not in data:
                        data[key] = default[key]
                return data
            except (json.JSONDecodeError, IOError):
                return default
        return default

    def _save_stats(self):
        os.makedirs(os.path.dirname(self.stats_path), exist_ok=True)
        with open(self.stats_path, "w", encoding="utf-8") as f:
            json.dump(self.scan_stats, f, indent=2, ensure_ascii=False)

    def _increment_stats(self, verdict: str):
        self.scan_stats["total_scans"] += 1
        if verdict == "ILEGAL":
            self.scan_stats["illegal_count"] += 1
        elif verdict == "LEGAL":
            self.scan_stats["legal_count"] += 1
        self._save_stats()

    def _save_training_image(self, image_base64: str, batch_id: str):
        """Guarda imagen raw para entrenamiento YOLO."""
        if not config.TRAINING_IMAGES_ENABLED:
            print("[Training] DESACTIVADO por config")
            return None

        try:
            count = self._count_training_images()
            if count >= config.TRAINING_IMAGES_TARGET:
                print(f"[Training] Target alcanzado ({count}/{config.TRAINING_IMAGES_TARGET})")
                return None

            today = datetime.now().strftime("%Y-%m-%d")
            day_dir = os.path.join(config.TRAINING_IMAGES_DIR, today)
            print(f"[Training] Creando directorio: {day_dir}")
            os.makedirs(day_dir, exist_ok=True)

            img_data = image_base64
            if "," in img_data:
                img_data = img_data.split(",", 1)[1]

            img_path = os.path.join(day_dir, f"scan_{batch_id}.jpg")
            raw_bytes = base64.b64decode(img_data)
            with open(img_path, "wb") as f:
                f.write(raw_bytes)

            size_kb = len(raw_bytes) / 1024
            print(f"[Training] Imagen guardada: {img_path} ({size_kb:.0f} KB) [{count+1}/{config.TRAINING_IMAGES_TARGET}]")
            return img_path
        except Exception as e:
            print(f"[Training] ERROR guardando imagen: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _save_training_metadata(self, img_path: str, batch_id: str,
                                banknotes: list):
        """Guarda metadata JSON junto a la imagen (en background thread)."""
        def _save():
            try:
                meta_path = img_path.replace(".jpg", ".json")
                metadata = {
                    "batch_id": batch_id,
                    "timestamp": datetime.now().isoformat(),
                    "bills_detected": len(banknotes),
                    "banknotes": [
                        {
                            "denomination": b.get("denomination"),
                            "serial": b.get("serial"),
                            "series": b.get("series", ""),
                            "verdict": b.get("verdict", ""),
                        }
                        for b in banknotes
                    ],
                }
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(metadata, f, indent=2, ensure_ascii=False)
            except Exception as e:
                print(f"[Training] Error guardando metadata: {e}")

        threading.Thread(target=_save, daemon=True).start()

    def _count_training_images(self) -> int:
        """Cuenta imagenes .jpg en el directorio de training."""
        base = config.TRAINING_IMAGES_DIR
        if not os.path.exists(base):
            return 0
        count = 0
        for dirpath, _, filenames in os.walk(base):
            count += sum(1 for f in filenames if f.endswith(".jpg"))
        return count

    def get_training_status(self) -> dict:
        """Retorna estado de la recoleccion de imagenes de entrenamiento."""
        count = self._count_training_images()
        disk_mb = 0.0
        base = config.TRAINING_IMAGES_DIR
        dir_exists = os.path.exists(base)
        writable = os.access(base, os.W_OK) if dir_exists else False

        if dir_exists:
            for dirpath, _, filenames in os.walk(base):
                for f in filenames:
                    try:
                        disk_mb += os.path.getsize(os.path.join(dirpath, f))
                    except OSError:
                        pass
            disk_mb /= (1024 * 1024)

        # Test de escritura rapido
        write_test = "no probado"
        if dir_exists and writable:
            test_path = os.path.join(base, ".write_test")
            try:
                with open(test_path, "w") as f:
                    f.write("ok")
                os.remove(test_path)
                write_test = "ok"
            except Exception as e:
                write_test = f"error: {e}"

        return {
            "enabled": config.TRAINING_IMAGES_ENABLED,
            "collected": count,
            "target": config.TRAINING_IMAGES_TARGET,
            "disk_usage_mb": round(disk_mb, 1),
            "ready": count >= config.TRAINING_IMAGES_TARGET,
            "diagnostics": {
                "images_dir": config.TRAINING_IMAGES_DIR,
                "dir_exists": dir_exists,
                "writable": writable,
                "write_test": write_test,
                "data_dir": config.DATA_DIR,
            },
            "detection": {
                "phase": "yolo" if self.bill_detector.yolo_available else "opencv",
                "active": True,
            },
        }

    def scan_image(self, image_base64: str) -> dict:
        """Flujo completo: imagen -> deteccion -> recorte -> OCR -> verificacion.
        Soporta multiples billetes en una sola imagen."""

        # Paso 0: Generar batch_id y guardar imagen para entrenamiento
        batch_id = str(uuid.uuid4())[:8]
        training_img_path = self._save_training_image(image_base64, batch_id)

        # Paso 1: Detectar y recortar billetes individuales
        crops = self.bill_detector.detect_and_crop(image_base64)
        detected_count = sum(1 for c in crops if c.get("confidence", 0) > 0)

        if detected_count > 1:
            # Multiples billetes detectados: OCR individual por recorte
            print(f"[Detector] {detected_count} billetes detectados, OCR individual")
            ocr_results = []
            for i, crop in enumerate(crops):
                print(f"[Detector] OCR billete {i+1}/{detected_count}")
                result = self.ocr.extract_single_bill(crop["image"])
                if result and result.get("success"):
                    ocr_results.append(result)

            # Fallback: si los recortes no dieron resultado, OCR con imagen completa
            if not ocr_results:
                print("[Detector] Recortes fallaron, intentando OCR imagen completa")
                ocr_results = self.ocr.extract_from_image(image_base64)
        else:
            # Un billete o deteccion fallo: usar flujo original (multi-billete)
            ocr_results = self.ocr.extract_from_image(image_base64)

        # Filtrar resultados exitosos
        successful = [r for r in ocr_results if r.get("success")]

        if not successful:
            first = ocr_results[0] if ocr_results else {}
            return {
                "success": False,
                "step_failed": "ocr",
                "no_banknotes": first.get("no_banknotes", False),
                "ocr_result": first,
                "message": first.get(
                    "error", "No se pudo procesar la imagen."
                ),
            }

        banknotes = []

        for ocr_result in successful:
            denomination = ocr_result.get("denomination")
            serial = ocr_result.get("serial")

            if not denomination or not serial:
                continue

            verification = self.verify_serial(denomination, serial, track=False)
            verification["ocr_result"] = ocr_result
            verification["series"] = ocr_result.get("series", "")

            self.database.record_scan(
                denomination=denomination,
                serial=serial,
                series=ocr_result.get("series", ""),
                verdict=verification["verdict"],
                risk_level=verification["risk_level"],
                confidence=verification["confidence"],
                method="scan",
                raw_ocr_text=ocr_result.get("raw_text", ""),
                batch_id=batch_id if len(successful) > 1 else "",
                tokens_used=ocr_result.get("tokens_used", 0),
            )
            self._increment_stats(verification["verdict"])
            banknotes.append(verification)

        if not banknotes:
            return {
                "success": False,
                "step_failed": "extraction",
                "ocr_result": successful[0],
                "message": "No se pudo extraer la denominacion o el numero de serie.",
            }

        # Build summary
        summary = {
            "total": len(banknotes),
            "legal": sum(1 for b in banknotes if b["verdict"] == "LEGAL"),
            "illegal": sum(1 for b in banknotes if b["verdict"] == "ILEGAL"),
            "suspicious": sum(1 for b in banknotes if b["verdict"] == "SOSPECHOSO"),
        }

        # Build response with backward compat (spread first banknote at top level)
        result = {
            "success": True,
            "batch_id": batch_id,
            "banknotes": banknotes,
            "summary": summary,
        }
        # Backward compat: top-level fields from first banknote
        result.update(banknotes[0])

        # Guardar metadata de entrenamiento (background thread)
        if training_img_path:
            self._save_training_metadata(training_img_path, batch_id, banknotes)

        return result

    def verify_serial(self, denomination: int, serial: int, track: bool = True) -> dict:
        """Verifica un serial contra la DB del BCB y la red neuronal."""
        db_result = self.db.is_illegal(denomination, serial)
        nn_result = self.nn.predict_banknote(denomination, serial)

        if db_result["illegal"]:
            verdict = "ILEGAL"
            confidence = 1.0
            risk_level = "ALTO"
        elif nn_result["model_trained"] and nn_result["probability"] > 0.7:
            verdict = "SOSPECHOSO"
            confidence = nn_result["probability"]
            risk_level = "MEDIO"
        else:
            verdict = "LEGAL"
            confidence = 1.0 - nn_result.get("probability", 0)
            risk_level = "BAJO"

        if track:
            self.database.record_scan(
                denomination=denomination,
                serial=serial,
                series="",
                verdict=verdict,
                risk_level=risk_level,
                confidence=confidence,
                method="manual",
            )
            self._increment_stats(verdict)

        return {
            "success": True,
            "denomination": denomination,
            "serial": serial,
            "verdict": verdict,
            "risk_level": risk_level,
            "confidence": confidence,
            "db_check": db_result,
            "nn_prediction": nn_result,
            "comunicado": "CP9/2026 - 28 de febrero de 2026",
        }

    def train_model(self, epochs=100, learning_rate=0.05, samples=8000):
        """Entrena la red neuronal y guarda los pesos."""
        result = self.nn.train(
            epochs=epochs, learning_rate=learning_rate, samples=samples
        )
        self.nn.save_weights(config.MODEL_WEIGHTS_PATH)
        self.db.save_to_json(config.BCB_DATA_PATH)
        return result

    def get_stats(self):
        """Retorna estadisticas del sistema."""
        db_stats = self.database.get_stats()
        recent = self.database.get_recent_scans(10)
        return {
            "bcb_database": self.db.get_stats(),
            "neural_network": self.nn.get_model_info(),
            "total_scans": db_stats["total_scans"],
            "illegal_count": db_stats["illegal_count"],
            "legal_count": db_stats["legal_count"],
            "suspicious_count": db_stats["suspicious_count"],
            "recent_scans": recent,
        }

    def get_history(self, page=1, per_page=20, verdict_filter=None,
                    denomination_filter=None):
        """Retorna historial paginado desde la base de datos."""
        return self.database.get_history(
            page=page,
            per_page=per_page,
            verdict_filter=verdict_filter,
            denomination_filter=denomination_filter,
        )

    def get_ranges(self):
        """Retorna los rangos del BCB."""
        return self.db.get_all_ranges_flat()

    def get_chart_data(self, days=30):
        """Retorna datos agregados por dia para graficas."""
        return self.database.get_chart_data(days)

    def test_api(self):
        """Prueba la conexion con el servicio OCR."""
        return self.ocr.test_connection()
