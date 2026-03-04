"""
Servicio OCR usando LM Studio REST API nativo (accesible por Tailscale VPN).
Envia imagenes de billetes para extraer numero de serie, denominacion y serie.
Soporta multiples billetes en una sola imagen.
Endpoint: /api/v1/chat
"""

import base64
import json
import re
import time
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
    "Esta imagen contiene uno o mas billetes bolivianos fisicos. "
    "IGNORA completamente cualquier texto que NO sea parte de un billete "
    "(numeros de telefono, comentarios, logos, marcas de agua de apps, "
    "texto de interfaz, emojis, nombres de usuario). "
    "Solo lee el texto IMPRESO en los billetes fisicos.\n\n"
    "Para CADA billete visible, extrae:\n"
    "- Denominacion: el valor del billete (10, 20, 50, 100 o 200)\n"
    "- Serie: la letra mayuscula (A, B, C, etc.)\n"
    "- Serial: el numero de serie impreso (tipicamente 9 digitos)\n\n"
    "Responde con este formato para CADA billete:\n"
    "---BILLETE---\n"
    "Denominacion: [numero]\n"
    "Serie: [letra]\n"
    "Serial: [numero]\n\n"
    "Si hay varios billetes, repite el bloque ---BILLETE--- para cada uno. "
    "Si solo hay uno, usa el mismo formato una vez."
)

FALLBACK_PROMPT = "Lee todo el texto visible en esta imagen"


class OCRService:
    def __init__(self):
        self.api_url = config.LM_STUDIO_API_URL
        self.model = config.VISION_MODEL
        self.fallback_model = config.FALLBACK_VISION_MODEL

    @staticmethod
    def _normalize_orientation(image_base64: str) -> str:
        """Normalize EXIF orientation, resize to max 1024px, return base64."""
        try:
            img = Image.open(BytesIO(base64.b64decode(image_base64)))
            img = ImageOps.exif_transpose(img)
            if img.mode == "RGBA":
                img = img.convert("RGB")
            img.thumbnail((1024, 1024))
            buf = BytesIO()
            img.save(buf, format="JPEG", quality=85)
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception:
            return image_base64

    def extract_from_image(self, image_base64: str) -> list:
        """
        Envia una imagen en base64 a LM Studio REST API nativo (/api/v1/chat).
        Soporta multiples billetes en una sola imagen.
        Retorna: lista de dicts con denomination, serial, series, raw_text
        """
        image_base64 = self._normalize_orientation(image_base64)
        print(f"[OCR] Image size: {len(image_base64)} bytes base64")

        # Intento 1: modelo principal con prompt estructurado
        print(f"[OCR] === Starting extraction with primary: {self.model} ===")
        results = self._call_vision_model(image_base64, self.model, PROMPT)
        if results:
            successful = [r for r in results if r.get("success")]
            if successful:
                print(f"[OCR] Primary model found {len(successful)} banknote(s)")
                return successful

        print(f"[OCR] Primary model failed or found 0 banknotes, trying fallback")
        # Intento 2: fallback con prompt estructurado primero, luego simple
        if self.fallback_model != self.model:
            # 2a: prompt estructurado (mejor para multi-billete)
            print(f"[OCR] === Fallback with structured prompt: {self.fallback_model} ===")
            fallback_results = self._call_vision_model(
                image_base64, self.fallback_model, PROMPT
            )
            if fallback_results:
                successful = [r for r in fallback_results if r.get("success")]
                if successful:
                    print(f"[OCR] Fallback structured found {len(successful)} banknote(s)")
                    return successful

            # 2b: prompt simple + regex como ultimo recurso
            print(f"[OCR] === Fallback with simple prompt: {self.fallback_model} ===")
            fallback_results = self._call_vision_model(
                image_base64, self.fallback_model, FALLBACK_PROMPT
            )
            if fallback_results:
                successful = [r for r in fallback_results if r.get("success")]
                if successful:
                    return successful
                raw = fallback_results[0].get("raw_response", "")
                if raw:
                    extracted = self._extract_all_from_text(raw)
                    if extracted:
                        return extracted

        # Retornar error
        if results and not any(r.get("success") for r in results):
            first = results[0]
            # Propagar no_banknotes si el modelo respondio pero no encontro billetes
            if first.get("no_banknotes"):
                return [first]
            return [{"success": False, "error": first.get("error", "No se pudo procesar la imagen."), "source": "lm_studio"}]
        return [{"success": False, "error": "No se pudo procesar la imagen.", "source": "lm_studio"}]

    # Timeout total por intento de generacion (segundos).
    # Evita que modelos lentos bloqueen indefinidamente en imagenes complejas.
    TOTAL_TIMEOUT = 90

    def _call_vision_model(self, image_base64: str, model: str,
                           prompt: str) -> list:
        """Llama a un modelo de vision en LM Studio y parsea la respuesta SSE.
        Reintenta hasta 1 vez en errores transitorios (red, 5xx, respuesta vacia).
        Retorna lista de resultados (uno por billete detectado)."""
        payload = {
            "model": model,
            "input": [
                {"type": "image", "data_url": f"data:image/jpeg;base64,{image_base64}"},
                {"type": "text", "content": prompt},
            ],
            "temperature": 0.1,
            "max_output_tokens": config.MAX_OUTPUT_TOKENS,
            "stream": True,
        }

        max_retries = 1
        for attempt in range(max_retries + 1):
            start_time = time.time()
            print(f"[OCR] Attempt {attempt+1}/{max_retries+1} with {model}")
            try:
                response = requests.post(
                    self.api_url,
                    json=payload,
                    timeout=(15, 120),
                    stream=True,
                )
                response.raise_for_status()

                content = ""
                timed_out = False
                for line in response.iter_lines():
                    elapsed = time.time() - start_time
                    if elapsed > self.TOTAL_TIMEOUT:
                        print(f"[OCR] Total timeout {self.TOTAL_TIMEOUT}s reached for {model} "
                              f"(got {len(content)} chars so far)")
                        timed_out = True
                        break
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
                        return [self._fallback_error(f"Error de LM Studio: {err_msg}")]
                    chunk_type = chunk.get("type", "")
                    if chunk_type == "message.delta":
                        # Formato nativo LM Studio (GLM)
                        content += chunk.get("content", "")
                    elif chunk_type == "chat.end":
                        break
                    elif "choices" in chunk:
                        # Formato OpenAI-compatible (MiniCPM y otros)
                        choice = chunk["choices"][0] if chunk["choices"] else {}
                        delta = choice.get("delta", {})
                        content += delta.get("content", "") or ""
                        if choice.get("finish_reason"):
                            break

                elapsed = time.time() - start_time
                print(f"[OCR] {model} responded: {len(content)} chars in {elapsed:.1f}s"
                      f"{' (TIMEOUT)' if timed_out else ''}")

                # Si se obtuvo contenido parcial por timeout, intentar parsearlo
                if timed_out and content:
                    print(f"[OCR] Attempting to parse partial content ({len(content)} chars)")

                if not content:
                    if attempt < max_retries:
                        time.sleep(3 * (attempt + 1))
                        continue
                    return [self._fallback_error("El modelo OCR no devolvio respuesta.")]

                tokens_used = len(content) // 4
                results = self._parse_multi_response(content)
                for r in results:
                    r["tokens_used"] = tokens_used
                print(f"[OCR] Parsed {len(results)} result(s), "
                      f"successful: {sum(1 for r in results if r.get('success'))}")
                return results

            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                elapsed = time.time() - start_time
                print(f"[OCR] HTTP {status} from {model} after {elapsed:.1f}s")
                if status >= 500 and attempt < max_retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                detail = ""
                try:
                    detail = e.response.json().get("error", "")
                    if isinstance(detail, dict):
                        detail = detail.get("message", "")
                except Exception:
                    pass
                return [self._fallback_error(
                    f"Error HTTP {status} de LM Studio. {detail}"
                )]

            except requests.exceptions.Timeout:
                elapsed = time.time() - start_time
                print(f"[OCR] Read timeout from {model} after {elapsed:.1f}s")
                return [self._fallback_error(
                    "Timeout: el servidor OCR no respondio a tiempo. "
                    "Verifique que LM Studio esta corriendo."
                )]

            except requests.exceptions.ConnectionError:
                elapsed = time.time() - start_time
                print(f"[OCR] Connection error to {model} after {elapsed:.1f}s")
                if attempt < max_retries:
                    time.sleep(3 * (attempt + 1))
                    continue
                return [self._fallback_error(
                    "No se pudo conectar con el servidor OCR. "
                    "Verifique que LM Studio esta corriendo en la red local."
                )]

            except Exception as e:
                print(f"[OCR] Unexpected error with {model}: {e}")
                return [self._fallback_error(f"Error inesperado: {str(e)}")]

        return [self._fallback_error("El OCR fallo despues de varios intentos.")]

    def _parse_multi_response(self, content: str) -> list:
        """Parsea respuesta que puede contener multiples billetes separados por ---BILLETE---."""
        # Limpiar tags especiales de glm-4v-flash
        content = re.sub(r'<\|[^|]*\|>', '', content).strip()

        # Split por delimitador
        blocks = re.split(r'---\s*BILLETE\s*---', content)
        blocks = [b.strip() for b in blocks if b.strip()]

        if not blocks:
            # Sin delimitadores: tratar como billete unico
            result = self._parse_single_block(content)
            if result:
                return [result]
            # Ultimo recurso: regex sobre texto completo
            return self._extract_all_from_text(content) or [{
                "success": False,
                "error": "No se detectaron billetes en la imagen. Asegurese de que los billetes sean visibles.",
                "no_banknotes": True,
                "raw_response": content,
                "source": "lm_studio",
            }]

        results = []
        seen_serials = set()
        for block in blocks:
            parsed = self._parse_single_block(block)
            if parsed and parsed.get("success"):
                serial = parsed.get("serial")
                if serial and serial not in seen_serials:
                    seen_serials.add(serial)
                    results.append(parsed)

        if results:
            return results

        # Fallback: extraer todo con regex
        all_extracted = self._extract_all_from_text(content)
        if all_extracted:
            return all_extracted

        return [{
            "success": False,
            "error": "No se detectaron billetes en la imagen. Asegurese de que los billetes sean visibles.",
            "no_banknotes": True,
            "raw_response": content,
            "source": "lm_studio",
        }]

    def _parse_single_block(self, content: str) -> dict:
        """Parsea un bloque de texto para un solo billete."""
        # Intento 1: formato estructurado "Denominacion: X, Serie: Y, Serial: Z"
        denom_match = re.search(r'[Dd]enominaci[oó]n:\s*(\d{2,3})', content)
        serial_match = re.search(r'[Ss]erial:\s*(\d{6,10})', content)
        series_match = re.search(r'[Ss]erie:\s*([A-Za-z])', content)

        if denom_match and serial_match:
            denomination = int(denom_match.group(1))
            serial = int(serial_match.group(1))
            series = series_match.group(1).upper() if series_match else ""

            if denomination in (10, 20, 50, 100, 200) and self._is_valid_serial(serial):
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

                if denomination and serial and self._is_valid_serial(serial):
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

        # Intento 3: regex del texto
        result = self._extract_from_text(content)
        if result:
            return result

        return None

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
            candidate = int(series_serial.group(2))
            if self._is_valid_serial(candidate):
                series = series_serial.group(1)
                serial = candidate

        # Patron: secuencia larga de digitos (6-10)
        if not serial:
            all_numbers = re.findall(r'\b(\d{6,10})\b', text)
            candidates = [int(n) for n in all_numbers if self._is_valid_serial(int(n))]
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

    def _extract_all_from_text(self, text: str) -> list:
        """Extrae TODOS los billetes posibles del texto crudo usando regex."""
        text_upper = text.upper()

        # Buscar todos los pares serie+serial
        all_matches = re.findall(r'\b([A-Z])\s*(\d{6,10})\b', text_upper)
        if not all_matches:
            # Buscar solo numeros largos
            all_numbers = re.findall(r'\b(\d{6,10})\b', text)
            if not all_numbers:
                return []
            all_matches = [("", n) for n in all_numbers]

        # Extraer denominacion del texto (sera la misma para todos si solo hay una)
        denomination = self._extract_denomination(text)

        results = []
        seen_serials = set()
        for series, serial_str in all_matches:
            serial = int(serial_str)
            if serial in seen_serials:
                continue
            if not self._is_valid_serial(serial):
                continue
            seen_serials.add(serial)
            if denomination:
                results.append({
                    "success": True,
                    "denomination": denomination,
                    "serial": serial,
                    "series": series,
                    "raw_text": text,
                    "source": "lm_studio",
                })

        return results if results else []

    def _extract_denomination(self, text: str) -> int:
        """Extrae la denominacion del texto."""
        text_upper = text.upper()
        text_lower = text.lower()

        bs_match = re.search(r'BS\.?\s*(\d{2,3})', text_upper)
        if bs_match:
            val = int(bs_match.group(1))
            if val in (10, 20, 50, 100, 200):
                return val

        boliv_match = re.search(r'(\d{2,3})\s*BOLIVIANO', text_upper)
        if boliv_match:
            val = int(boliv_match.group(1))
            if val in (10, 20, 50, 100, 200):
                return val

        for word, val in DENOM_MAP.items():
            if word in text_lower:
                return val

        for num_str in ("200", "100", "50", "20", "10"):
            pattern = r'(?<!\d)' + num_str + r'(?!\d)'
            if re.search(pattern, text):
                return int(num_str)

        return None

    @staticmethod
    def _is_valid_serial(serial: int, denomination: int = None) -> bool:
        """Valida que un numero parezca serial de billete boliviano."""
        s = str(serial)
        # Seriales bolivianos tipicamente tienen 7-9 digitos
        if len(s) < 7 or len(s) > 10:
            return False
        # Rechazar numeros que parezcan telefonos bolivianos (8 digitos empezando con 6 o 7)
        if len(s) == 8 and s[0] in ('6', '7'):
            return False
        return True

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
