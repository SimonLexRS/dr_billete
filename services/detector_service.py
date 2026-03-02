"""
Servicio Detector: orquesta OCR + Base de datos BCB + Red Neuronal
para generar un veredicto completo sobre un billete.
"""

import json
import os
import uuid

from models.bcb_database import BCBDatabase
from models.neural_network import NeuralNetwork
from services.ocr_service import OCRService
from services.database_service import DatabaseService
import config


class DetectorService:
    def __init__(self):
        self.db = BCBDatabase()
        self.nn = NeuralNetwork()
        self.ocr = OCRService()
        self.database = DatabaseService()
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
        """Flujo completo: imagen -> OCR -> verificacion -> resultado.
        Soporta multiples billetes en una sola imagen."""
        ocr_results = self.ocr.extract_from_image(image_base64)

        # Filtrar resultados exitosos
        successful = [r for r in ocr_results if r.get("success")]

        if not successful:
            first = ocr_results[0] if ocr_results else {}
            return {
                "success": False,
                "step_failed": "ocr",
                "ocr_result": first,
                "message": first.get(
                    "error", "No se pudo procesar la imagen."
                ),
            }

        batch_id = str(uuid.uuid4())[:8]
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

    def test_api(self):
        """Prueba la conexion con el servicio OCR."""
        return self.ocr.test_connection()
