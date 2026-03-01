"""
Servicio OCR usando DeepSeek-VL2 via SiliconFlow API (compatible con OpenAI).
Envia imagenes de billetes para extraer numero de serie, denominacion y serie.
"""

import base64
import json
import re
import requests
import config


class OCRService:
    def __init__(self):
        self.api_key = config.SILICONFLOW_API_KEY
        self.api_url = config.SILICONFLOW_API_URL
        self.model = config.VISION_MODEL

    def extract_from_image(self, image_base64: str) -> dict:
        """
        Envia una imagen en base64 a DeepSeek-VL2 para extraer datos del billete.
        Retorna: denomination, serial, series, raw_text
        """
        if not self.api_key:
            return self._fallback_error(
                "API key de SiliconFlow no configurada. "
                "Configure SILICONFLOW_API_KEY en las variables de entorno."
            )

        prompt = """Analiza esta imagen de un billete boliviano y extrae la siguiente informacion.
Responde UNICAMENTE con un JSON valido, sin texto adicional ni markdown:

{
  "denomination": <numero entero: 10, 20, 50, 100 o 200>,
  "serial": <numero de serie como entero, sin letras ni guiones>,
  "series": "<letra de la serie, ejemplo: B>",
  "raw_text": "<todo el texto visible en el billete>"
}

Si no puedes identificar algún campo, usa null para ese campo.
Es MUY IMPORTANTE extraer el numero de serie correctamente.
El numero de serie suele estar impreso en rojo o negro,
y puede tener un prefijo de letras seguido de numeros."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

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
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime};base64,{image_base64}",
                                "detail": "high",
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            "max_tokens": 500,
            "temperature": 0.1,
        }

        try:
            response = requests.post(
                self.api_url, headers=headers, json=payload, timeout=60
            )
            response.raise_for_status()
            data = response.json()

            if "error" in data:
                err_msg = data["error"].get("message", str(data["error"]))
                return self._fallback_error(f"Error de la API: {err_msg}")

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
                f"Error HTTP {status} de la API. {detail}"
            )
        except requests.exceptions.Timeout:
            return self._fallback_error("Timeout: la API no respondio a tiempo.")
        except requests.exceptions.ConnectionError:
            return self._fallback_error("No se pudo conectar con la API de SiliconFlow.")
        except Exception as e:
            return self._fallback_error(f"Error inesperado: {str(e)}")

    def _parse_response(self, content: str) -> dict:
        """Parsea la respuesta de DeepSeek-VL2 extrayendo el JSON."""
        content = content.strip()

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

                return {
                    "success": True,
                    "denomination": denomination,
                    "serial": serial,
                    "series": parsed.get("series", ""),
                    "raw_text": parsed.get("raw_text", ""),
                    "source": "deepseek_vl2_ocr",
                }
            except (json.JSONDecodeError, ValueError):
                pass

        return {
            "success": False,
            "error": "No se pudo interpretar la respuesta del OCR.",
            "raw_response": content,
            "source": "deepseek_vl2_ocr",
        }

    @staticmethod
    def _fallback_error(message: str) -> dict:
        return {
            "success": False,
            "error": message,
            "source": "deepseek_vl2_ocr",
        }

    def test_connection(self) -> dict:
        """Prueba la conexion con la API de SiliconFlow/DeepSeek-VL2."""
        if not self.api_key:
            return {"connected": False, "error": "SILICONFLOW_API_KEY no configurada"}
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": "Responde solo: OK"}],
            "max_tokens": 10,
        }
        try:
            resp = requests.post(
                self.api_url, headers=headers, json=payload, timeout=10
            )
            resp.raise_for_status()
            return {"connected": True, "model": self.model}
        except Exception as e:
            return {"connected": False, "error": str(e)}
