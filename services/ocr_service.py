"""
Servicio OCR usando Ollama local (accesible por Tailscale VPN).
Envia imagenes de billetes para extraer numero de serie, denominacion y serie.
"""

import json
import re
import requests
import config


class OCRService:
    def __init__(self):
        self.api_url = config.OLLAMA_API_URL
        self.model = config.VISION_MODEL

    def extract_from_image(self, image_base64: str) -> dict:
        """
        Envia una imagen en base64 a Ollama para extraer datos del billete.
        Retorna: denomination, serial, series, raw_text
        """
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
            "max_tokens": 500,
            "temperature": 0.1,
        }

        try:
            response = requests.post(
                self.api_url,
                json=payload,
                timeout=120,
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
        """Parsea la respuesta del modelo de vision extrayendo el JSON."""
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
                    "source": "ollama_local",
                }
            except (json.JSONDecodeError, ValueError):
                pass

        return {
            "success": False,
            "error": "No se pudo interpretar la respuesta del OCR.",
            "raw_response": content,
            "source": "ollama_local",
        }

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
            # Ollama health check
            base_url = self.api_url.rsplit("/v1/", 1)[0]
            resp = requests.get(f"{base_url}/api/version", timeout=5)
            resp.raise_for_status()
            version = resp.json().get("version", "unknown")
            return {"connected": True, "model": self.model, "ollama_version": version}
        except Exception as e:
            return {"connected": False, "error": str(e)}
