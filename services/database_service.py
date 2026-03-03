"""
Servicio de base de datos SQLite para Dr. Billetes.
Almacena historial de escaneos y estadisticas de forma persistente.
"""

import json
import os
import random
import sqlite3
from datetime import datetime, timedelta, timezone

import config

DB_PATH = getattr(config, "DATABASE_PATH", os.path.join(config.DATA_DIR, "dr_billetes.db"))


class DatabaseService:
    def __init__(self, db_path=None):
        self.db_path = db_path or DB_PATH
        self._init_db()
        self._migrate_json_stats()
        self._seed_initial_data()

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = self._get_conn()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS scans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
                    denomination INTEGER,
                    serial INTEGER,
                    series TEXT DEFAULT '',
                    verdict TEXT NOT NULL,
                    risk_level TEXT DEFAULT '',
                    confidence REAL DEFAULT 0.0,
                    method TEXT NOT NULL DEFAULT 'manual',
                    raw_ocr_text TEXT DEFAULT ''
                );

                CREATE INDEX IF NOT EXISTS idx_scans_timestamp
                    ON scans(timestamp DESC);
                CREATE INDEX IF NOT EXISTS idx_scans_verdict
                    ON scans(verdict);
                CREATE INDEX IF NOT EXISTS idx_scans_denomination
                    ON scans(denomination);
            """)
            conn.commit()

            # Migration: add batch_id column if missing
            columns = [row[1] for row in conn.execute("PRAGMA table_info(scans)").fetchall()]
            if "batch_id" not in columns:
                conn.execute("ALTER TABLE scans ADD COLUMN batch_id TEXT DEFAULT ''")
                conn.commit()
            if "tokens_used" not in columns:
                conn.execute("ALTER TABLE scans ADD COLUMN tokens_used INTEGER DEFAULT 0")
                conn.commit()
        finally:
            conn.close()

    def _migrate_json_stats(self):
        """Migracion unica: importar conteos de scan_stats.json."""
        json_path = config.SCAN_STATS_PATH
        if not os.path.exists(json_path):
            return

        conn = self._get_conn()
        try:
            count = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
            if count > 0:
                return

            with open(json_path, "r", encoding="utf-8") as f:
                stats = json.load(f)

            ts = datetime.now(timezone.utc).isoformat()
            illegal = stats.get("illegal_count", 0)
            legal = stats.get("legal_count", 0)

            if illegal > 0 or legal > 0:
                rows = []
                for _ in range(illegal):
                    rows.append((ts, "ILEGAL", "migrated"))
                for _ in range(legal):
                    rows.append((ts, "LEGAL", "migrated"))
                conn.executemany(
                    "INSERT INTO scans (timestamp, verdict, method) VALUES (?, ?, ?)",
                    rows,
                )
                conn.commit()
                print(f"[DatabaseService] Migrados {illegal} ilegales + {legal} legales desde JSON.")
        except Exception as e:
            print(f"[DatabaseService] Advertencia en migracion: {e}")
        finally:
            conn.close()

    def _seed_initial_data(self):
        """Insert 40 seed records if the database is completely empty.
        Distribution: 36 legal (90%), 4 illegal (10%).
        """
        conn = self._get_conn()
        try:
            count = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
            if count > 0:
                return

            base_time = datetime.now(timezone.utc) - timedelta(days=7)
            rows = []

            # 4 illegal scans
            for i, denom in enumerate([50, 20, 50, 10]):
                ts = (base_time + timedelta(hours=i * 4)).isoformat()
                serial = random.randint(80000000, 99999999)
                rows.append((ts, denom, serial, "B", "ILEGAL", "ALTO", 1.0, "seed", ""))

            # 36 legal scans
            legal_denoms = [10, 20, 50, 100, 200] * 8
            for i, denom in enumerate(legal_denoms[:36]):
                ts = (base_time + timedelta(hours=(i + 4) * 2)).isoformat()
                serial = random.randint(10000000, 79999999)
                rows.append((ts, denom, serial, "B", "LEGAL", "BAJO", 0.95, "seed", ""))

            conn.executemany(
                """INSERT INTO scans
                   (timestamp, denomination, serial, series, verdict,
                    risk_level, confidence, method, raw_ocr_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
            conn.commit()
            print(f"[DatabaseService] Seeded {len(rows)} initial records (4 illegal, 36 legal).")
        except Exception as e:
            print(f"[DatabaseService] Warning during seeding: {e}")
        finally:
            conn.close()

    def record_scan(self, denomination, serial, series, verdict, risk_level,
                    confidence, method, raw_ocr_text="", batch_id="",
                    tokens_used=0):
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO scans
                    (timestamp, denomination, serial, series, verdict,
                     risk_level, confidence, method, raw_ocr_text, batch_id,
                     tokens_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(),
                denomination, serial, series or "",
                verdict, risk_level, confidence, method, raw_ocr_text or "",
                batch_id or "", tokens_used or 0,
            ))
            conn.commit()
        finally:
            conn.close()

    def get_stats(self):
        conn = self._get_conn()
        try:
            row = conn.execute("""
                SELECT
                    COUNT(*) as total_scans,
                    SUM(CASE WHEN verdict = 'ILEGAL' THEN 1 ELSE 0 END) as illegal_count,
                    SUM(CASE WHEN verdict = 'LEGAL' THEN 1 ELSE 0 END) as legal_count,
                    SUM(CASE WHEN verdict = 'SOSPECHOSO' THEN 1 ELSE 0 END) as suspicious_count
                FROM scans
            """).fetchone()
            return {
                "total_scans": row["total_scans"] or 0,
                "illegal_count": row["illegal_count"] or 0,
                "legal_count": row["legal_count"] or 0,
                "suspicious_count": row["suspicious_count"] or 0,
            }
        finally:
            conn.close()

    def get_recent_scans(self, limit=10):
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT id, timestamp, denomination, serial, series, verdict,
                       risk_level, confidence, method
                FROM scans
                WHERE method NOT IN ('migrated', 'seed')
                ORDER BY id DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    def get_history(self, page=1, per_page=20, verdict_filter=None,
                    denomination_filter=None):
        conn = self._get_conn()
        try:
            where_clauses = ["method NOT IN ('migrated', 'seed')"]
            params = []

            if verdict_filter:
                where_clauses.append("verdict = ?")
                params.append(verdict_filter)
            if denomination_filter:
                where_clauses.append("denomination = ?")
                params.append(int(denomination_filter))

            where_sql = "WHERE " + " AND ".join(where_clauses)

            total = conn.execute(
                f"SELECT COUNT(*) FROM scans {where_sql}", params
            ).fetchone()[0]

            offset = (page - 1) * per_page
            rows = conn.execute(
                f"""SELECT id, timestamp, denomination, serial, series, verdict,
                           risk_level, confidence, method
                    FROM scans {where_sql}
                    ORDER BY id DESC
                    LIMIT ? OFFSET ?""",
                params + [per_page, offset],
            ).fetchall()

            return {
                "scans": [dict(row) for row in rows],
                "total": total,
                "page": page,
                "per_page": per_page,
                "total_pages": (total + per_page - 1) // per_page if total > 0 else 0,
            }
        finally:
            conn.close()

    def get_chart_data(self, days=30):
        """Retorna datos agregados por dia para graficas."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT DATE(timestamp) as day,
                       SUM(CASE WHEN verdict='LEGAL' THEN 1 ELSE 0 END) as legal,
                       SUM(CASE WHEN verdict='ILEGAL' THEN 1 ELSE 0 END) as illegal,
                       SUM(CASE WHEN verdict='SOSPECHOSO' THEN 1 ELSE 0 END) as suspicious,
                       SUM(tokens_used) as tokens
                FROM scans
                WHERE timestamp >= datetime('now', ?)
                  AND method NOT IN ('migrated', 'seed')
                GROUP BY DATE(timestamp)
                ORDER BY day ASC
            """, (f'-{days} days',)).fetchall()
            return {
                "days": [r["day"] for r in rows],
                "legal": [r["legal"] for r in rows],
                "illegal": [r["illegal"] for r in rows],
                "suspicious": [r["suspicious"] for r in rows],
                "tokens": [r["tokens"] or 0 for r in rows],
            }
        finally:
            conn.close()
