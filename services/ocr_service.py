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
    "diez": 10, "10": 10,
    "veinte": 20, "20": 20,
    "cincuenta": 50, "50": 50,
    "cien": 100, "100": 100,
    "doscientos": 200, "200": 200,
}


class OCRService:
    def __init__(self):
        self.api_url = config.OLLAMA_API_URL
        self.model = config.VISION_MODEL

    def extract_from_image(self, image_base64: str) -> dict:
        """
        Envia una imagen en base64 a Ollama para extraer datos del billete.
        Retorna: denomination, serial, series, raw_text
        """
        prompt = "Text Recognition: Lee todo el texto visible en esta imagen de un billete boliviano. Incluye todos los numeros y letras que veas."

        mime = "image/jpeg"
        if image_base64[:4] == "iVBO":
            mime = "image/png"
        elif image_base64[:4] == "AAAA":
            mime = "image/webp"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{image_base64}"
                            },
                        },
                    ],
                }
            ],
            "max_tokens": 800,
            "temperature": 0.1,
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
                err_msg = data["error"].get("message", str(data["error"]))
                return self._fallback_error(f"Error de Ollama: {err_msg}")

            content = data["choices"][0]["message"]["content"]
            return self._parse_response(content)

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else "unknown"
            detail = ""
            try:
                detail = e.response.json().get("error", {}).get("message", "")
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
            "error": "No se pudo interpretar la respuesta del OCR.",
            "raw_response": content,
            "source": "ollama_local",
        }

    def _extract_from_text(self, text: str) -> dict:
        """Extrae denominacion, serial y serie del texto crudo usando regex."""
        text_lower = text.lower()

        # Extraer denominacion
        denomination = None
        # Buscar "Bs. 20", "Bs 50", "Bs.20", etc.
        bs_match = re.search(r'bs\.?\s*(\d{2,3})', text_lower)
        if bs_match:
            val = int(bs_match.group(1))
            if val in (10, 20, 50, 100, 200):
                denomination = val

        # Buscar palabras: "veinte bolivianos", "cincuenta", etc.
        if not denomination:
            for word, val in DENOM_MAP.items():
                if word in text_lower and not word.isdigit():
                    denomination = val
                    break

        # Buscar numeros sueltos que coincidan con denominaciones
        if not denomination:
            for num_str in ("200", "100", "50", "20", "10"):
                if num_str in text:
                    denomination = int(num_str)
                    break

        # Extraer serie (letra sola antes de numeros, ej: "B 097000123")
        series = ""
        series_match = re.search(r'\b([A-Z])\s+(\d{6,})', text)
        if series_match:
            series = series_match.group(1)

        # Extraer numero de serie (secuencia larga de digitos, 6-10 digitos)
        serial = None
        # Patron 1: letra + espacio + digitos (ej: "B 097000123")
        serial_match = re.search(r'[A-Z]\s+(\d{6,10})', text)
        if serial_match:
            serial = int(serial_match.group(1))

        # Patron 2: secuencia de digitos larga sin contexto
        if not serial:
            all_numbers = re.findall(r'\d{6,10}', text)
            # Filtrar los que no son anos (2026, etc.)
            candidates = [int(n) for n in all_numbers if len(n) >= 6]
            if candidates:
                serial = candidates[0]

        # Patron 3: digitos con separadores (ej: "097.000.123" o "097 000 123")
        if not serial:
            spaced = re.search(r'(\d{2,3}[\s.]?\d{3}[\s.]?\d{3})', text)
            if spaced:
                serial = int(re.sub(r'[\s.]', '', spaced.group(1)))

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
            base_url = self.api_url.rsplit("/v1/", 1)[0]
            resp = requests.get(f"{base_url}/api/version", timeout=5)
            resp.raise_for_status()
            version = resp.json().get("version", "unknown")
            return {"connected": True, "model": self.model, "ollama_version": version}
        except Exception as e:
            return {"connected": False, "error": str(e)}
