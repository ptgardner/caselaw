"""Storage backends for NCAT decisions.

Supports:
- JSON: Single file with all decisions
- JSONL: One JSON object per line (streaming-friendly, resumable)
- SQLite: Queryable database with full-text search
"""

import json
import sqlite3
from pathlib import Path
from typing import Iterator

from .models import Decision


class JSONStorage:
    """Traditional JSON file storage."""

    def __init__(self, path: str):
        self.path = Path(path)

    def save(self, decisions: list[Decision], indent: int = 2) -> None:
        """Save all decisions to JSON file."""
        data = {"decisions": [d.to_dict() for d in decisions]}
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)

    def load(self) -> list[Decision]:
        """Load all decisions from JSON file."""
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [Decision(**d) for d in data.get("decisions", [])]


class JSONLStorage:
    """JSONL storage - one decision per line.

    Benefits:
    - Streaming writes (append without rewriting)
    - Easy resume after interruption
    - Memory efficient for large datasets
    """

    def __init__(self, path: str):
        self.path = Path(path)

    def append(self, decision: Decision) -> None:
        """Append a single decision to the file."""
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(decision.to_dict(), ensure_ascii=False) + "\n")

    def append_many(self, decisions: list[Decision]) -> None:
        """Append multiple decisions to the file."""
        with open(self.path, "a", encoding="utf-8") as f:
            for d in decisions:
                f.write(json.dumps(d.to_dict(), ensure_ascii=False) + "\n")

    def load(self) -> list[Decision]:
        """Load all decisions from JSONL file."""
        if not self.path.exists():
            return []
        decisions = []
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    decisions.append(Decision(**json.loads(line)))
        return decisions

    def iter_decisions(self) -> Iterator[Decision]:
        """Iterate over decisions without loading all into memory."""
        if not self.path.exists():
            return
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    yield Decision(**json.loads(line))

    def get_scraped_urls(self) -> set[str]:
        """Get set of URLs already scraped."""
        return {d.url for d in self.iter_decisions()}

    def count(self) -> int:
        """Count number of decisions in file."""
        if not self.path.exists():
            return 0
        count = 0
        with open(self.path, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    count += 1
        return count


class SQLiteStorage:
    """SQLite storage with queryable schema.

    Schema:
    - decisions: main table with all fields
    - grounds: junction table for grounds_of_appeal
    - successful_grounds: junction table for successful grounds
    - decision_makers: junction table for decision makers

    Enables queries like:
    - SELECT * FROM decisions WHERE outcome = 'allowed'
    - SELECT * FROM decisions WHERE id IN (SELECT decision_id FROM grounds WHERE ground = 'ev_no_evidence')
    """

    SCHEMA = """
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE NOT NULL,
        medium_neutral_citation TEXT NOT NULL,
        year INTEGER NOT NULL,
        decision_type TEXT NOT NULL,
        outcome TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS decision_makers (
        decision_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        FOREIGN KEY (decision_id) REFERENCES decisions(id),
        PRIMARY KEY (decision_id, name)
    );

    CREATE TABLE IF NOT EXISTS grounds (
        decision_id INTEGER NOT NULL,
        ground TEXT NOT NULL,
        FOREIGN KEY (decision_id) REFERENCES decisions(id),
        PRIMARY KEY (decision_id, ground)
    );

    CREATE TABLE IF NOT EXISTS successful_grounds (
        decision_id INTEGER NOT NULL,
        ground TEXT NOT NULL,
        FOREIGN KEY (decision_id) REFERENCES decisions(id),
        PRIMARY KEY (decision_id, ground)
    );

    CREATE INDEX IF NOT EXISTS idx_decisions_year ON decisions(year);
    CREATE INDEX IF NOT EXISTS idx_decisions_type ON decisions(decision_type);
    CREATE INDEX IF NOT EXISTS idx_decisions_outcome ON decisions(outcome);
    CREATE INDEX IF NOT EXISTS idx_grounds_ground ON grounds(ground);
    """

    def __init__(self, path: str):
        self.path = Path(path)
        self.conn = None

    def connect(self) -> None:
        """Connect to database and create schema if needed."""
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(self.SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        """Close database connection."""
        if self.conn:
            self.conn.close()
            self.conn = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def insert(self, decision: Decision) -> int:
        """Insert a single decision. Returns the decision ID."""
        cursor = self.conn.cursor()

        # Insert main decision
        cursor.execute("""
            INSERT OR REPLACE INTO decisions
            (url, medium_neutral_citation, year, decision_type, outcome)
            VALUES (?, ?, ?, ?, ?)
        """, (
            decision.url,
            decision.medium_neutral_citation,
            decision.year,
            decision.decision_type,
            decision.outcome,
        ))
        decision_id = cursor.lastrowid

        # Clear existing related data (for upsert behavior)
        cursor.execute("DELETE FROM decision_makers WHERE decision_id = ?", (decision_id,))
        cursor.execute("DELETE FROM grounds WHERE decision_id = ?", (decision_id,))
        cursor.execute("DELETE FROM successful_grounds WHERE decision_id = ?", (decision_id,))

        # Insert decision makers
        for name in decision.decision_makers:
            cursor.execute(
                "INSERT INTO decision_makers (decision_id, name) VALUES (?, ?)",
                (decision_id, name)
            )

        # Insert grounds
        for ground in decision.grounds_of_appeal:
            cursor.execute(
                "INSERT INTO grounds (decision_id, ground) VALUES (?, ?)",
                (decision_id, ground)
            )

        # Insert successful grounds
        for ground in decision.successful_grounds:
            cursor.execute(
                "INSERT INTO successful_grounds (decision_id, ground) VALUES (?, ?)",
                (decision_id, ground)
            )

        self.conn.commit()
        return decision_id

    def insert_many(self, decisions: list[Decision]) -> None:
        """Insert multiple decisions in a transaction."""
        for d in decisions:
            self.insert(d)

    def get_by_url(self, url: str) -> Decision | None:
        """Get a decision by URL."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM decisions WHERE url = ?", (url,))
        row = cursor.fetchone()
        if not row:
            return None
        return self._row_to_decision(row)

    def get_all(self) -> list[Decision]:
        """Get all decisions."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM decisions ORDER BY year DESC, id DESC")
        return [self._row_to_decision(row) for row in cursor.fetchall()]

    def get_scraped_urls(self) -> set[str]:
        """Get set of URLs already in database."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT url FROM decisions")
        return {row[0] for row in cursor.fetchall()}

    def count(self) -> int:
        """Count total decisions."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM decisions")
        return cursor.fetchone()[0]

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        """Execute a custom query."""
        cursor = self.conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()

    def get_by_ground(self, ground: str) -> list[Decision]:
        """Get all decisions with a specific ground of appeal."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT d.* FROM decisions d
            JOIN grounds g ON d.id = g.decision_id
            WHERE g.ground = ?
            ORDER BY d.year DESC
        """, (ground,))
        return [self._row_to_decision(row) for row in cursor.fetchall()]

    def get_by_outcome(self, outcome: str) -> list[Decision]:
        """Get all decisions with a specific outcome."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT * FROM decisions WHERE outcome = ? ORDER BY year DESC",
            (outcome,)
        )
        return [self._row_to_decision(row) for row in cursor.fetchall()]

    def get_statistics(self) -> dict:
        """Get summary statistics."""
        cursor = self.conn.cursor()

        stats = {}

        # Total count
        cursor.execute("SELECT COUNT(*) FROM decisions")
        stats["total"] = cursor.fetchone()[0]

        # By type
        cursor.execute("""
            SELECT decision_type, COUNT(*) as count
            FROM decisions GROUP BY decision_type
        """)
        stats["by_type"] = {row[0]: row[1] for row in cursor.fetchall()}

        # By outcome
        cursor.execute("""
            SELECT outcome, COUNT(*) as count
            FROM decisions WHERE outcome IS NOT NULL
            GROUP BY outcome
        """)
        stats["by_outcome"] = {row[0]: row[1] for row in cursor.fetchall()}

        # By year
        cursor.execute("""
            SELECT year, COUNT(*) as count
            FROM decisions GROUP BY year ORDER BY year DESC
        """)
        stats["by_year"] = {row[0]: row[1] for row in cursor.fetchall()}

        # Top grounds
        cursor.execute("""
            SELECT ground, COUNT(*) as count
            FROM grounds GROUP BY ground ORDER BY count DESC LIMIT 10
        """)
        stats["top_grounds"] = {row[0]: row[1] for row in cursor.fetchall()}

        return stats

    def _row_to_decision(self, row: sqlite3.Row) -> Decision:
        """Convert a database row to a Decision object."""
        decision_id = row["id"]
        cursor = self.conn.cursor()

        # Get decision makers
        cursor.execute(
            "SELECT name FROM decision_makers WHERE decision_id = ?",
            (decision_id,)
        )
        decision_makers = [r[0] for r in cursor.fetchall()]

        # Get grounds
        cursor.execute(
            "SELECT ground FROM grounds WHERE decision_id = ?",
            (decision_id,)
        )
        grounds = [r[0] for r in cursor.fetchall()]

        # Get successful grounds
        cursor.execute(
            "SELECT ground FROM successful_grounds WHERE decision_id = ?",
            (decision_id,)
        )
        successful_grounds = [r[0] for r in cursor.fetchall()]

        return Decision(
            url=row["url"],
            medium_neutral_citation=row["medium_neutral_citation"],
            year=row["year"],
            decision_makers=decision_makers,
            decision_type=row["decision_type"],
            grounds_of_appeal=grounds,
            outcome=row["outcome"],
            successful_grounds=successful_grounds,
        )
