"""
Servicio de deteccion de billetes: identifica y recorta billetes individuales
de una imagen usando deteccion de contornos (OpenCV) o modelo YOLO (ONNX).

Fase 1: OpenCV contour detection (sin modelo ML)
Fase 2: YOLOv8-nano ONNX inference (futuro)
"""

import base64
import io
import os

import cv2
import numpy as np
from PIL import Image

import config


class BillDetectorService:
    def __init__(self):
        self.yolo_available = False
        self.session = None
        self.max_bills = getattr(config, "BILL_DETECTION_MAX_BILLS", 10)
        self.crop_padding = getattr(config, "BILL_CROP_PADDING", 0.08)
        self.min_confidence = getattr(config, "BILL_DETECTION_CONFIDENCE", 0.5)

        # Intentar cargar modelo YOLO ONNX si existe
        model_path = getattr(config, "BILL_DETECTOR_MODEL_PATH", None)
        if model_path and os.path.exists(model_path):
            try:
                import onnxruntime as ort
                self.session = ort.InferenceSession(model_path)
                self.yolo_available = True
                print("[BillDetector] Modelo YOLO ONNX cargado.")
            except Exception as e:
                print(f"[BillDetector] No se pudo cargar modelo ONNX: {e}")

        if not self.yolo_available:
            print("[BillDetector] Usando deteccion por contornos (OpenCV).")

    def detect_and_crop(self, image_base64: str) -> list[dict]:
        """
        Detecta billetes en la imagen y retorna recortes individuales.

        Returns:
            Lista de dicts con:
                - "image": base64 del recorte
                - "bbox": (x, y, w, h) del bounding box
                - "confidence": confianza de la deteccion
            Si no detecta nada, retorna [{"image": imagen_original, ...}]
        """
        try:
            if self.yolo_available:
                results = self._detect_yolo(image_base64)
            else:
                results = self._detect_contours(image_base64)

            if results and len(results) > 0:
                print(f"[BillDetector] {len(results)} billete(s) detectado(s).")
                return results[:self.max_bills]
        except Exception as e:
            print(f"[BillDetector] Error en deteccion: {e}")

        # Fallback: retornar imagen original como unico "recorte"
        return [{"image": image_base64, "bbox": None, "confidence": 0.0}]

    def _decode_image(self, image_base64: str) -> np.ndarray:
        """Decodifica base64 a numpy array BGR (formato OpenCV)."""
        # Remover prefijo data:image/...;base64, si existe
        if "," in image_base64:
            image_base64 = image_base64.split(",", 1)[1]

        img_bytes = base64.b64decode(image_base64)
        img_array = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_COLOR)
        return img

    def _encode_image(self, img: np.ndarray, quality: int = 85) -> str:
        """Codifica numpy array BGR a base64 JPEG."""
        _, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])
        b64 = base64.b64encode(buffer).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    def _detect_contours(self, image_base64: str) -> list[dict]:
        """
        Detecta billetes usando deteccion de contornos con OpenCV.
        Busca rectangulos con aspect ratio de billete (1.8 - 3.0).
        """
        img = self._decode_image(image_base64)
        if img is None:
            return []

        h, w = img.shape[:2]
        img_area = h * w

        # Preprocesamiento para deteccion de bordes
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Deteccion de bordes adaptativa
        # Usar multiples umbrales para mejor deteccion
        results = []

        for method in ["canny", "adaptive"]:
            if method == "canny":
                edges = cv2.Canny(blurred, 30, 100)
            else:
                thresh = cv2.adaptiveThreshold(
                    blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                    cv2.THRESH_BINARY_INV, 11, 2
                )
                edges = cv2.Canny(thresh, 30, 100)

            # Dilatar para cerrar gaps en los bordes
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            edges = cv2.dilate(edges, kernel, iterations=2)

            contours, _ = cv2.findContours(
                edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )

            for contour in contours:
                # Filtrar por area minima (al menos 3% de la imagen)
                area = cv2.contourArea(contour)
                if area < img_area * 0.03:
                    continue

                # Aproximar a poligono
                peri = cv2.arcLength(contour, True)
                approx = cv2.approxPolyDP(contour, 0.02 * peri, True)

                # Buscar rectangulos (4-6 vertices por tolerancia)
                if len(approx) < 4 or len(approx) > 8:
                    continue

                # Obtener bounding box rotado
                rect = cv2.minAreaRect(contour)
                box_w, box_h = rect[1]

                if box_w == 0 or box_h == 0:
                    continue

                # Aspect ratio (siempre largo/corto)
                aspect = max(box_w, box_h) / min(box_w, box_h)

                # Billetes bolivianos: ~155mm x 70mm = ratio ~2.2
                # Tolerancia amplia: 1.6 a 3.2
                if aspect < 1.6 or aspect > 3.2:
                    continue

                # Calcular confianza basada en cuanto se parece a un rectangulo
                rect_area = box_w * box_h
                rectangularity = area / rect_area if rect_area > 0 else 0

                if rectangularity < 0.6:
                    continue

                # Obtener bounding box alineado con ejes + padding
                x, y, bw, bh = cv2.boundingRect(contour)
                crop = self._crop_with_padding(img, x, y, bw, bh, h, w)

                if crop is not None:
                    results.append({
                        "image": self._encode_image(crop),
                        "bbox": (x, y, bw, bh),
                        "confidence": rectangularity,
                        "area": area,
                    })

        # Eliminar duplicados (bounding boxes que se solapan mucho)
        results = self._remove_overlapping(results)

        # Ordenar por posicion (izquierda a derecha, arriba a abajo)
        results.sort(key=lambda r: (r["bbox"][1], r["bbox"][0]))

        # Limpiar campo auxiliar
        for r in results:
            r.pop("area", None)

        return results

    def _crop_with_padding(self, img: np.ndarray, x: int, y: int,
                           bw: int, bh: int, img_h: int, img_w: int) -> np.ndarray:
        """Recorta una region de la imagen con padding adicional."""
        pad_x = int(bw * self.crop_padding)
        pad_y = int(bh * self.crop_padding)

        x1 = max(0, x - pad_x)
        y1 = max(0, y - pad_y)
        x2 = min(img_w, x + bw + pad_x)
        y2 = min(img_h, y + bh + pad_y)

        crop = img[y1:y2, x1:x2]

        if crop.size == 0:
            return None

        return crop

    def _remove_overlapping(self, results: list[dict],
                            iou_threshold: float = 0.5) -> list[dict]:
        """Elimina detecciones solapadas, manteniendo la de mayor confianza."""
        if len(results) <= 1:
            return results

        # Ordenar por confianza descendente
        results.sort(key=lambda r: r["confidence"], reverse=True)

        keep = []
        for i, r in enumerate(results):
            is_duplicate = False
            for kept in keep:
                iou = self._compute_iou(r["bbox"], kept["bbox"])
                if iou > iou_threshold:
                    is_duplicate = True
                    break
            if not is_duplicate:
                keep.append(r)

        return keep

    def _compute_iou(self, box1: tuple, box2: tuple) -> float:
        """Calcula Intersection over Union entre dos bounding boxes (x,y,w,h)."""
        x1, y1, w1, h1 = box1
        x2, y2, w2, h2 = box2

        # Coordenadas de interseccion
        ix1 = max(x1, x2)
        iy1 = max(y1, y2)
        ix2 = min(x1 + w1, x2 + w2)
        iy2 = min(y1 + h1, y2 + h2)

        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0

        intersection = (ix2 - ix1) * (iy2 - iy1)
        area1 = w1 * h1
        area2 = w2 * h2
        union = area1 + area2 - intersection

        return intersection / union if union > 0 else 0.0

    def _detect_yolo(self, image_base64: str) -> list[dict]:
        """
        Detecta billetes usando modelo YOLOv8-nano ONNX.
        Placeholder para Fase 2.
        """
        # TODO: Implementar cuando el modelo ONNX este entrenado
        # 1. Decodificar imagen
        # 2. Resize a 640x640, normalizar a [0,1]
        # 3. self.session.run() para inference
        # 4. Post-process: NMS, filtrar por confianza
        # 5. Recortar cada deteccion
        return []
