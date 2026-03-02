"""
Servicio OCR usando LM Studio REST API nativo (accesible por Tailscale VPN).
Envia imagenes de billetes para extraer numero de serie, denominacion y serie.
Endpoint: /api/v1/chat
"""

import base64
import json
import re
from io import BytesIO

import requests
from PIL import Image, ImageOps

import config


# Mapeo de texto a denominacion
DENOM_MAP = {
    "diez": 10,
    "veinte": 20,
    "cincuenta": 50,
    "cien": 100,
    "doscientos": 200,
}

PROMPT = (
    "Esta es una imagen de un billete boliviano. "
    "La imagen puede estar rotada o inclinada. "
    "Identifica la denominacion (10, 20, 50, 100 o 200 bolivianos), "
    "el numero de serie (6-10 digitos) y la letra de serie. "
    "Responde UNICAMENTE con:\n"
    "Denominacion: [numero]\n"
    "Serie: [letra]\n"
    "Serial: [numero]"
)

FALLBACK_PROMPT = "Lee todo el texto visible en esta imagen"


class OCRService:
    def __init__(self):
        self.api_url = config.LM_STUDIO_API_URL
        self.model = config.VISION_MODEL
        self.fallback_model = config.FALLBACK_VISION_MODEL

    @staticmethod
    def _normalize_orientation(image_base64: str) -> str:
        """Normalize EXIF orientation and return corrected base64."""
        try:
            img = Image.open(BytesIO(base64.b64decode(image_base64)))
            img = ImageOps.exif_transpose(img)
            if img.mode == "RGBA":
                img = img.convert("RGB")
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=90)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            return image_base64

    def extract_from_image(self, image_base64: str) -> dict:
        """
        Envia una imagen en base64 a LM Studio REST API nativo (/api/v1/chat).
        Usa el modelo principal (glm-4.6v-flash) con prompt estructurado.
        Si falla, intenta con fallback (glm-ocr) + prompt simple + regex.
        Retorna: denomination, serial, series, raw_text
        """
        image_base64 = self._normalize_orientation(image_base64)

        # Intento 1: modelo principal con prompt estructurado
        result = self._call_vision_model(image_base64, self.model, PROMPT)
        if result.get("success"):
            return result

        # Intento 2: fallback con modelo OCR simple + regex parsing
        if self.fallback_model != self.model:
            fallback_result = self._call_vision_model(
                image_base64, self.fallback_model, FALLBACK_PROMPT
            )
            if fallback_result.get("success"):
                return fallback_result
            # Si el fallback obtuvo texto crudo, intentar extraer con regex
            raw = fallback_result.get("raw_response", "")
            if raw:
                extracted = self._extract_from_text(raw)
                if extracted:
                    return extracted

        return result  # Retornar el error del intento principal

    def _call_vision_model(self, image_base64: str, model: str,
                           prompt: str) -> dict:
        """Llama a un modelo de vision en LM Studio y parsea la respuesta."""
        payload = {
            "model": model,
            "input": [
                {"type": "image", "data_url": f"data:image/jpeg;base64,{image_base64}"},
                {"type": "text", "content": prompt},
            ],
            "temperature": 0.1,
            "max_output_tokens": 500,
            "stream": True,
        }

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=(30, 300),
                stream=True,
            )
            response.raise_for_status()

            content = ""
            for line in response.iter_lines():
                if not line:
                    continue

                line_str = line.decode("utf-8") if isinstance(line, bytes) else line

                if line_str.startswith("data: "):
                    line_str = line_str[6:]
                elif line_str.startswith("event: "):
                    continue

                if line_str.strip() == "[DONE]":
                    break

                try:
                    chunk = json.loads(line_str)
                except json.JSONDecodeError:
                    continue

                if "error" in chunk:
                    err_msg = chunk["error"]
                    if isinstance(err_msg, dict):
                        err_msg = err_msg.get("message", str(err_msg))
                    return self._fallback_error(f"Error de LM Studio: {err_msg}")

                chunk_type = chunk.get("type", "")
                if chunk_type == "message.delta":
                    content += chunk.get("content", "")
                elif chunk_type == "chat.end":
                    break

            if not content:
                return self._fallback_error("El modelo OCR no devolvio respuesta.")

            return self._parse_response(content)

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "unknown"
            detail = ""
            try:
                detail = e.response.json().get("error", "")
                if isinstance(detail, dict):
                    detail = detail.get("message", "")
            except Exception:
                pass
            return self._fallback_error(
                f"Error HTTP {status} de LM Studio. {detail}"
            )
        except requests.exceptions.Timeout:
            return self._fallback_error(
                "Timeout: el servidor OCR no respondio a tiempo. "
                "Verifique que LM Studio esta corriendo."
            )
        except requests.exceptions.ConnectionError:
            return self._fallback_error(
                "No se pudo conectar con el servidor OCR. "
                "Verifique que LM Studio esta corriendo en la red local."
            )
        except Exception as e:
            return self._fallback_error(f"Error inesperado: {str(e)}")

    def _parse_response(self, content: str) -> dict:
        """Parsea la respuesta del modelo."""
        # Limpiar tags especiales de glm-4v-flash
        content = re.sub(r'<\|[^|]*\|>', '', content).strip()

        # Intento 1: buscar formato estructurado "Denominacion: X, Serie: Y, Serial: Z"
        denom_match = re.search(r'[Dd]enominaci[oó]n:\s*(\d{2,3})', content)
        serial_match = re.search(r'[Ss]erial:\s*(\d{6,10})', content)
        series_match = re.search(r'[Ss]erie:\s*([A-Za-z])', content)

        if denom_match and serial_match:
            denomination = int(denom_match.group(1))
            serial = int(serial_match.group(1))
            series = series_match.group(1).upper() if series_match else ""

            if denomination in (10, 20, 50, 100, 200):
                return {
                    "success": True,
                    "denomination": denomination,
                    "serial": serial,
                    "series": series,
                    "raw_text": content,
                    "source": "lm_studio",
                }

        # Intento 2: buscar JSON en la respuesta
        json_match = re.search(r"\{[\s\S]*\}", content)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                serial = parsed.get("serial")
                if isinstance(serial, str):
                    serial = int(re.sub(r"[^0-9]", "", serial) or "0")
                denomination = parsed.get("denomination")
                if isinstance(denomination, str):
                    denomination = int(re.sub(r"[^0-9]", "", denomination) or "0")

                if denomination and serial:
                    return {
                        "success": True,
                        "denomination": denomination,
                        "serial": serial,
                        "series": parsed.get("series", ""),
                        "raw_text": parsed.get("raw_text", content),
                        "source": "lm_studio",
                    }
            except (json.JSONDecodeError, ValueError):
                pass

        # Intento 3: extraer datos con regex del texto crudo
        result = self._extract_from_text(content)
        if result:
            return result

        return {
            "success": False,
            "error": f"OCR leyo: {content[:200]}",
            "raw_response": content,
            "source": "lm_studio",
        }

    def _extract_from_text(self, text: str) -> dict:
        """Extrae denominacion, serial y serie del texto crudo usando regex."""
        text_upper = text.upper()
        text_lower = text.lower()

        # Extraer denominacion
        denomination = None

        # Buscar "Bs. 20", "Bs 50", "Bs.20", "BS 10", etc.
        bs_match = re.search(r'BS\.?\s*(\d{2,3})', text_upper)
        if bs_match:
            val = int(bs_match.group(1))
            if val in (10, 20, 50, 100, 200):
                denomination = val

        # Buscar "BOLIVIANOS" con numero cercano
        if not denomination:
            boliv_match = re.search(r'(\d{2,3})\s*BOLIVIANO', text_upper)
            if boliv_match:
                val = int(boliv_match.group(1))
                if val in (10, 20, 50, 100, 200):
                    denomination = val

        # Buscar palabras: "veinte", "cincuenta", "diez", etc.
        if not denomination:
            for word, val in DENOM_MAP.items():
                if word in text_lower:
                    denomination = val
                    break

        # Buscar numeros que coincidan con denominaciones (priorizar mayores)
        if not denomination:
            for num_str in ("200", "100", "50", "20", "10"):
                pattern = r'(?<!\d)' + num_str + r'(?!\d)'
                if re.search(pattern, text):
                    denomination = int(num_str)
                    break

        # Extraer serie y serial
        series = ""
        serial = None

        # Patron: letra + espacio/sin espacio + digitos (ej: "B 097000123", "B097000123")
        series_serial = re.search(r'\b([A-Z])\s*(\d{6,10})\b', text_upper)
        if series_serial:
            series = series_serial.group(1)
            serial = int(series_serial.group(2))

        # Patron: secuencia larga de digitos (6-10)
        if not serial:
            all_numbers = re.findall(r'\b(\d{6,10})\b', text)
            candidates = [int(n) for n in all_numbers]
            if candidates:
                serial = candidates[0]

        # Patron: digitos con separadores (ej: "097.000.123")
        if not serial:
            spaced = re.search(r'(\d{2,3}[\s.\-]\d{3}[\s.\-]\d{3})', text)
            if spaced:
                cleaned = re.sub(r'[\s.\-]', '', spaced.group(1))
                if len(cleaned) >= 6:
                    serial = int(cleaned)

        # Patron: numeros de 5+ digitos como ultimo recurso
        if not serial:
            nums = re.findall(r'\d{5,}', text)
            candidates = [int(n) for n in nums if int(n) > 99999]
            if candidates:
                serial = candidates[0]

        if denomination and serial:
            return {
                "success": True,
                "denomination": denomination,
                "serial": serial,
                "series": series,
                "raw_text": text,
                "source": "lm_studio",
            }

        return None

    @staticmethod
    def _fallback_error(message: str) -> dict:
        return {
            "success": False,
            "error": message,
            "source": "lm_studio",
        }

    def test_connection(self) -> dict:
        """Prueba la conexion con LM Studio REST API nativo."""
        try:
            base_url = self.api_url.rsplit("/api/", 1)[0]
            resp = requests.get(f"{base_url}/api/v1/models", timeout=5)
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models", data.get("data", []))
            model_ids = [m.get("key", m.get("id", "unknown")) for m in models]
            return {
                "connected": True,
                "model": self.model,
                "fallback_model": self.fallback_model,
                "available_models": model_ids,
            }
        except Exception as e:
            return {"connected": False, "error": str(e)}
