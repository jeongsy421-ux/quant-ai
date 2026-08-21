"""
==============================================
PERSONAL FINANCE - 저장소 (SQLite)
==============================================
외부 의존성 없이 표준 sqlite3만 사용한다.
DB 파일 기본 위치: backend/finance/data/finance.db  (.gitignore 대상)
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterable, Iterator, Optional

from .models import Profile, Transaction, UNCATEGORIZED

DEFAULT_DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "finance.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    txn_date     TEXT    NOT NULL,
    amount       INTEGER NOT NULL,
    description  TEXT    NOT NULL DEFAULT '',
    norm_desc    TEXT    NOT NULL DEFAULT '',
    institution  TEXT    NOT NULL DEFAULT '',
    account      TEXT    NOT NULL DEFAULT '',
    source       TEXT    NOT NULL DEFAULT 'manual',
    category     TEXT    NOT NULL DEFAULT '미분류',
    balance      INTEGER,
    memo         TEXT    NOT NULL DEFAULT '',
    installment  INTEGER NOT NULL DEFAULT 0,
    raw          TEXT,
    fingerprint  TEXT    NOT NULL UNIQUE,
    created_at   TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(txn_date);
CREATE INDEX IF NOT EXISTS idx_txn_cat  ON transactions(category);
CREATE INDEX IF NOT EXISTS idx_txn_norm ON transactions(norm_desc);

-- 사용자가 직접 고친 분류를 기억해서 다음부터 자동 적용 (학습)
CREATE TABLE IF NOT EXISTS category_rules (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern    TEXT NOT NULL UNIQUE,   -- norm_desc 부분문자열
    category   TEXT NOT NULL,
    hits       INTEGER NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT 'user',  -- user | builtin
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE TABLE IF NOT EXISTS budgets (
    month    TEXT NOT NULL,
    category TEXT NOT NULL,
    amount   INTEGER NOT NULL,
    PRIMARY KEY (month, category)
);

CREATE TABLE IF NOT EXISTS kv (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS import_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    source      TEXT NOT NULL,
    detail      TEXT NOT NULL DEFAULT '',
    inserted    INTEGER NOT NULL DEFAULT 0,
    duplicated  INTEGER NOT NULL DEFAULT 0,
    ran_at      TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);
"""


class FinanceDB:
    """가계부 저장소"""

    def __init__(self, path: str = DEFAULT_DB):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ── 기본 ──
    @contextmanager
    def cursor(self) -> Iterator[sqlite3.Cursor]:
        cur = self._conn.cursor()
        try:
            yield cur
            self._conn.commit()
        finally:
            cur.close()

    def close(self) -> None:
        self._conn.close()

    # ── 거래 ──
    def add_transactions(self, txns: Iterable[Transaction]) -> tuple[int, int]:
        """거래 일괄 저장. 반환 (신규 저장 수, 중복 스킵 수)"""
        inserted = duplicated = 0
        with self.cursor() as cur:
            for t in txns:
                row = t.to_row()
                cols = ", ".join(row.keys())
                marks = ", ".join("?" for _ in row)
                try:
                    cur.execute(
                        f"INSERT INTO transactions ({cols}) VALUES ({marks})",
                        list(row.values()),
                    )
                    inserted += 1
                except sqlite3.IntegrityError:
                    duplicated += 1
        return inserted, duplicated

    def query(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        category: Optional[str] = None,
        include_transfer: bool = False,
        limit: Optional[int] = None,
    ) -> list[Transaction]:
        sql = "SELECT * FROM transactions WHERE 1=1"
        args: list[Any] = []
        if start:
            sql += " AND txn_date >= ?"
            args.append(start)
        if end:
            sql += " AND txn_date <= ?"
            args.append(end)
        if category:
            sql += " AND category = ?"
            args.append(category)
        if not include_transfer:
            sql += " AND category != '이체'"
        sql += " ORDER BY txn_date DESC, id DESC"
        if limit:
            sql += f" LIMIT {int(limit)}"
        with self.cursor() as cur:
            rows = cur.execute(sql, args).fetchall()
        return [Transaction.from_row(r) for r in rows]

    def uncategorized(self, limit: int = 200) -> list[Transaction]:
        return self.query(category=UNCATEGORIZED, include_transfer=True, limit=limit)

    def set_category(self, txn_id: int, category: str, learn: bool = True) -> None:
        """단건 분류 수정 + 같은 가맹점에 규칙 학습"""
        with self.cursor() as cur:
            row = cur.execute(
                "SELECT norm_desc FROM transactions WHERE id = ?", (txn_id,)
            ).fetchone()
            if row is None:
                raise KeyError(f"거래 {txn_id} 없음")
            cur.execute("UPDATE transactions SET category = ? WHERE id = ?", (category, txn_id))
        if learn and row["norm_desc"]:
            self.learn_rule(row["norm_desc"], category)
            self.apply_rule(row["norm_desc"], category)

    def months(self) -> list[str]:
        with self.cursor() as cur:
            rows = cur.execute(
                "SELECT DISTINCT substr(txn_date,1,7) m FROM transactions ORDER BY m"
            ).fetchall()
        return [r["m"] for r in rows]

    def count(self) -> int:
        with self.cursor() as cur:
            return cur.execute("SELECT COUNT(*) c FROM transactions").fetchone()["c"]

    # ── 분류 규칙 ──
    def learn_rule(self, pattern: str, category: str, source: str = "user") -> None:
        with self.cursor() as cur:
            cur.execute(
                """INSERT INTO category_rules (pattern, category, hits, source)
                   VALUES (?, ?, 1, ?)
                   ON CONFLICT(pattern) DO UPDATE SET
                     category = excluded.category,
                     hits = category_rules.hits + 1,
                     updated_at = datetime('now','localtime')""",
                (pattern.strip(), category, source),
            )

    def user_rules(self) -> list[tuple[str, str]]:
        with self.cursor() as cur:
            rows = cur.execute(
                "SELECT pattern, category FROM category_rules ORDER BY length(pattern) DESC"
            ).fetchall()
        return [(r["pattern"], r["category"]) for r in rows]

    def apply_rule(self, pattern: str, category: str) -> int:
        """기존 거래에도 소급 적용"""
        with self.cursor() as cur:
            cur.execute(
                "UPDATE transactions SET category = ? WHERE norm_desc LIKE ?",
                (category, f"%{pattern}%"),
            )
            return cur.rowcount

    def update_categories(self, updates: dict[int, str]) -> int:
        with self.cursor() as cur:
            cur.executemany(
                "UPDATE transactions SET category = ? WHERE id = ?",
                [(c, i) for i, c in updates.items()],
            )
            return len(updates)

    # ── 예산 ──
    def save_budget(self, month: str, budget: dict[str, int]) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM budgets WHERE month = ?", (month,))
            cur.executemany(
                "INSERT INTO budgets (month, category, amount) VALUES (?,?,?)",
                [(month, c, int(a)) for c, a in budget.items()],
            )

    def load_budget(self, month: str) -> dict[str, int]:
        with self.cursor() as cur:
            rows = cur.execute(
                "SELECT category, amount FROM budgets WHERE month = ?", (month,)
            ).fetchall()
        return {r["category"]: r["amount"] for r in rows}

    # ── 프로필 ──
    def save_profile(self, profile: Profile) -> None:
        self.set_kv("profile", profile.to_json())

    def load_profile(self) -> Profile:
        raw = self.get_kv("profile")
        return Profile.from_dict(json.loads(raw)) if raw else Profile()

    # ── KV ──
    def set_kv(self, key: str, value: str) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO kv (key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

    def get_kv(self, key: str) -> Optional[str]:
        with self.cursor() as cur:
            row = cur.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    # ── 임포트 로그 ──
    def log_import(self, source: str, detail: str, inserted: int, duplicated: int) -> None:
        with self.cursor() as cur:
            cur.execute(
                "INSERT INTO import_log (source, detail, inserted, duplicated) VALUES (?,?,?,?)",
                (source, detail, inserted, duplicated),
            )

    def recent_imports(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            rows = cur.execute(
                "SELECT * FROM import_log ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]
