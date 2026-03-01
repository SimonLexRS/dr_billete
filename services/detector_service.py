"""
Servicio Detector: orquesta OCR + Base de datos BCB + Red Neuronal
para generar un veredicto completo sobre un billete.
"""

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

        # Intentar cargar pesos pre-entrenados
        if self.nn.load_weights(config.MODEL_WEIGHTS_PATH):
            print("[DetectorService] Modelo neuronal cargado desde disco.")
        else:
            print("[DetectorService] No hay modelo pre-entrenado. Entrene desde el dashboard.")

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

        verification = self.verify_serial(denomination, serial)
        verification["ocr_result"] = ocr_result
        verification["series"] = ocr_result.get("series", "")

        self.scan_history.append({
            "denomination": denomination,
            "serial": serial,
            "result": verification["verdict"],
            "method": "scan",
        })

        return verification

    def verify_serial(self, denomination: int, serial: int) -> dict:
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
            "total_scans": len(self.scan_history),
            "recent_scans": self.scan_history[-10:][::-1],
        }

    def get_ranges(self):
        """Retorna los rangos del BCB."""
        return self.db.get_all_ranges_flat()

    def test_api(self):
        """Prueba la conexion con DeepSeek."""
        return self.ocr.test_connection()
