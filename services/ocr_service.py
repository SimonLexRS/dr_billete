"""
Servicio OCR usando Ollama local (accesible por Tailscale VPN).
Envia imagenes de billetes para extraer numero de serie, denominacion y serie.
"""

import json
import re
import requests
import config


# Mapeo de texto a denominacion
DENOM_MAP = {
    "diez": 10,
    "veinte": 20,
    "cincuenta": 50,
    "cien": 100,
    "doscientos": 200,
}


class OCRService:
    def __init__(self):
        # Usar API nativa de Ollama para mejor soporte de vision
        base = config.OLLAMA_API_URL.rsplit("/v1/", 1)[0]
        self.api_url = f"{base}/api/chat"
        self.model = config.VISION_MODEL

    def extract_from_image(self, image_base64: str) -> dict:
        """
        Envia una imagen en base64 a Ollama para extraer datos del billete.
        Retorna: denomination, serial, series, raw_text
        """
        prompt = "Lee todo el texto visible en esta imagen de un billete boliviano. Incluye todos los numeros, letras y palabras que puedas leer."

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [image_base64],
                }
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 800,
            },
        }

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=60,
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                err_msg = data["error"] if isinstance(data["error"], str) else data["error"].get("message", str(data["error"]))
                return self._fallback_error(f"Error de Ollama: {err_msg}")

            content = data.get("message", {}).get("content", "")
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
                f"Error HTTP {status} de Ollama. {detail}"
            )
        except requests.exceptions.Timeout:
            return self._fallback_error(
                "Timeout: el servidor OCR no respondio a tiempo. "
                "Verifique que Ollama esta corriendo."
            )
        except requests.exceptions.ConnectionError:
            return self._fallback_error(
                "No se pudo conectar con el servidor OCR. "
                "Verifique que Ollama esta corriendo en la red local."
            )
        except Exception as e:
            return self._fallback_error(f"Error inesperado: {str(e)}")

    def _parse_response(self, content: str) -> dict:
        """Parsea la respuesta del modelo: intenta JSON primero, luego regex."""
        content = content.strip()

        # Intento 1: buscar JSON en la respuesta
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
                        "source": "ollama_local",
                    }
            except (json.JSONDecodeError, ValueError):
                pass

        # Intento 2: extraer datos con regex del texto crudo
        result = self._extract_from_text(content)
        if result:
            return result

        return {
            "success": False,
            "error": f"No se pudo extraer datos del billete. Texto OCR: {content[:300]}",
            "raw_response": content,
            "source": "ollama_local",
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

        # Buscar palabras: "veinte bolivianos", "cincuenta", "diez", etc.
        if not denomination:
            for word, val in DENOM_MAP.items():
                if word in text_lower:
                    denomination = val
                    break

        # Buscar numeros que coincidan con denominaciones (priorizar mayores)
        if not denomination:
            for num_str in ("200", "100", "50", "20", "10"):
                # Buscar como numero aislado (no parte de serial)
                pattern = r'(?<!\d)' + num_str + r'(?!\d{2,})'
                if re.search(pattern, text):
                    denomination = int(num_str)
                    break

        # Extraer serie (letra sola antes de numeros, ej: "B 097000123" o "B097000123")
        series = ""
        series_match = re.search(r'\b([A-Z])\s*(\d{6,})', text_upper)
        if series_match:
            series = series_match.group(1)

        # Extraer numero de serie
        serial = None

        # Patron 1: letra + espacio/sin espacio + digitos (ej: "B 097000123", "B097000123")
        serial_match = re.search(r'[A-Z]\s*(\d{6,10})', text_upper)
        if serial_match:
            serial = int(serial_match.group(1))

        # Patron 2: secuencia de digitos larga (6-10 digitos)
        if not serial:
            all_numbers = re.findall(r'\d{6,10}', text)
            candidates = [int(n) for n in all_numbers if len(n) >= 6]
            if candidates:
                serial = candidates[0]

        # Patron 3: digitos con separadores (ej: "097.000.123" o "097 000 123")
        if not serial:
            spaced = re.search(r'(\d{2,3}[\s.\-]?\d{3}[\s.\-]?\d{3})', text)
            if spaced:
                cleaned = re.sub(r'[\s.\-]', '', spaced.group(1))
                if len(cleaned) >= 6:
                    serial = int(cleaned)

        # Patron 4: Numeros de 5+ digitos (menos estricto)
        if not serial:
            nums = re.findall(r'\d{5,}', text)
            # Excluir anos y numeros cortos
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
                "source": "ollama_local",
            }

        return None

    @staticmethod
    def _fallback_error(message: str) -> dict:
        return {
            "success": False,
            "error": message,
            "source": "ollama_local",
        }

    def test_connection(self) -> dict:
        """Prueba la conexion con Ollama."""
        try:
            base_url = self.api_url.rsplit("/api/", 1)[0]
            resp = requests.get(f"{base_url}/api/version", timeout=5)
            resp.raise_for_status()
            version = resp.json().get("version", "unknown")
            return {"connected": True, "model": self.model, "ollama_version": version}
        except Exception as e:
            return {"connected": False, "error": str(e)}
