"""
Servicio Detector: orquesta OCR + Base de datos BCB + Red Neuronal
para generar un veredicto completo sobre un billete.
"""

import json
import os

from models.bcb_database import BCBDatabase
from models.neural_network import NeuralNetwork
from services.ocr_service import OCRService
import config


class DetectorService:
    def __init__(self):
        self.db = BCBDatabase()
        self.nn = NeuralNetwork()
        self.ocr = OCRService()
        self.scan_history = []
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

    def scan_image(self, image_base64: str) -> dict:
        """Flujo completo: imagen -> OCR -> verificacion -> resultado."""
        ocr_result = self.ocr.extract_from_image(image_base64)

        if not ocr_result.get("success"):
            return {
                "success": False,
                "step_failed": "ocr",
                "ocr_result": ocr_result,
                "message": ocr_result.get(
                    "error", "No se pudo procesar la imagen."
                ),
            }

        denomination = ocr_result.get("denomination")
        serial = ocr_result.get("serial")

        if not denomination or not serial:
            return {
                "success": False,
                "step_failed": "extraction",
                "ocr_result": ocr_result,
                "message": "No se pudo extraer la denominacion o el numero de serie.",
            }

        verification = self.verify_serial(denomination, serial, track=False)
        verification["ocr_result"] = ocr_result
        verification["series"] = ocr_result.get("series", "")

        self.scan_history.append({
            "denomination": denomination,
            "serial": serial,
            "result": verification["verdict"],
            "method": "scan",
        })
        self._increment_stats(verification["verdict"])

        return verification

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
            self.scan_history.append({
                "denomination": denomination,
                "serial": serial,
                "result": verdict,
                "method": "manual",
            })
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
        return {
            "bcb_database": self.db.get_stats(),
            "neural_network": self.nn.get_model_info(),
            "total_scans": self.scan_stats["total_scans"],
            "illegal_count": self.scan_stats["illegal_count"],
            "legal_count": self.scan_stats["legal_count"],
            "recent_scans": self.scan_history[-10:][::-1],
        }

    def get_ranges(self):
        """Retorna los rangos del BCB."""
        return self.db.get_all_ranges_flat()

    def test_api(self):
        """Prueba la conexion con el servicio OCR."""
        return self.ocr.test_connection()
