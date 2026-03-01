"""
Base de datos del BCB - Comunicado de Prensa CP9/2026 (28 de febrero de 2026)
Numeros de serie de los billetes de la Serie B que NO tienen valor legal.
"""

import json
import os

BCB_ILLEGAL_RANGES = {
    50: [
        (67250001, 67700000),
        (69050001, 69500000),
        (69500001, 69950000),
        (69950001, 70400000),
        (70400001, 70850000),
        (70850001, 71300000),
        (76310012, 85139995),
        (86400001, 86850000),
        (90900001, 91350000),
        (91800001, 92250000),
    ],
    20: [
        (87280145, 91646549),
        (96650001, 97100000),
        (99800001, 100250000),
        (100250001, 100700000),
        (109250001, 109700000),
        (110600001, 111050000),
        (111050001, 111500000),
        (111950001, 112400000),
        (112400001, 112850000),
        (112850001, 113300000),
        (114200001, 114650000),
        (114650001, 115100000),
        (115100001, 115550000),
        (118700001, 119150000),
        (119150001, 119600000),
        (120500001, 120950000),
    ],
    10: [
        (77100001, 77550000),
        (78000001, 78450000),
        (78900001, 96350000),
        (96350001, 96800000),
        (96800001, 97250000),
        (98150001, 98600000),
        (104900001, 105350000),
        (105350001, 105800000),
        (106700001, 107150000),
        (107600001, 108050000),
        (108050001, 108500000),
        (109400001, 109850000),
    ],
}

VALID_DENOMINATIONS = [10, 20, 50]


class BCBDatabase:
    def __init__(self):
        self.ranges = BCB_ILLEGAL_RANGES

    def is_illegal(self, denomination: int, serial: int) -> dict:
        """Verifica si un billete es ilegal segun la lista del BCB."""
        if denomination not in VALID_DENOMINATIONS:
            return {
                "illegal": False,
                "found": False,
                "message": f"Denominacion Bs{denomination} no esta en la lista del BCB.",
                "denomination": denomination,
                "serial": serial,
                "matching_range": None,
            }

        ranges = self.ranges.get(denomination, [])
        for start, end in ranges:
            if start <= serial <= end:
                return {
                    "illegal": True,
                    "found": True,
                    "message": f"BILLETE ILEGAL detectado. Serie {serial} de Bs{denomination} esta en el rango {start}-{end} del comunicado BCB CP9/2026.",
                    "denomination": denomination,
                    "serial": serial,
                    "matching_range": {"desde": start, "hasta": end},
                }

        return {
            "illegal": False,
            "found": True,
            "message": f"Billete LEGAL. Serie {serial} de Bs{denomination} no aparece en la lista del BCB.",
            "denomination": denomination,
            "serial": serial,
            "matching_range": None,
        }

    def get_ranges(self, denomination: int = None) -> dict:
        """Retorna los rangos ilegales, opcionalmente filtrados por denominacion."""
        if denomination:
            return {denomination: self.ranges.get(denomination, [])}
        return self.ranges

    def get_all_ranges_flat(self) -> list:
        """Retorna todos los rangos en formato plano para el frontend."""
        result = []
        for denom, ranges in self.ranges.items():
            for start, end in ranges:
                result.append({
                    "denomination": denom,
                    "desde": start,
                    "hasta": end,
                    "cantidad": end - start + 1,
                })
        return result

    def get_stats(self) -> dict:
        """Retorna estadisticas de la base de datos."""
        stats = {}
        total = 0
        for denom, ranges in self.ranges.items():
            count = sum(end - start + 1 for start, end in ranges)
            stats[f"Bs{denom}"] = {
                "rangos": len(ranges),
                "billetes_ilegales": count,
            }
            total += count
        stats["total_billetes_ilegales"] = total
        stats["total_rangos"] = sum(len(r) for r in self.ranges.values())
        stats["comunicado"] = "CP9/2026"
        stats["fecha"] = "28 de febrero de 2026"
        stats["serie"] = "B"
        return stats

    def save_to_json(self, path: str):
        """Guarda la base de datos en JSON."""
        data = {
            "comunicado": "CP9/2026",
            "fecha": "2026-02-28",
            "serie": "B",
            "ranges": {
                str(k): [{"desde": s, "hasta": e} for s, e in v]
                for k, v in self.ranges.items()
            },
        }
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
