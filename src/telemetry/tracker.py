"""
src/telemetry/tracker.py - SQLite-backed LLM Token & Cost Telemetry Engine

Tracks per-user API consumption, token metrics, and real-time USD cost estimation
for F.A.C.T. across Appraisal, Ask, Finder, and Contextualizer.
"""

import os
import sqlite3
import datetime
from typing import Dict, Any, List, Optional

DB_DIR = os.getenv("RESEARCH_EVAL_DATA_DIR", r"D:\SSD-Drive\Antigravity\ResearchEval\data")
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_DIR = os.getenv("RESEARCH_EVAL_DATA_DIR", os.path.join(PROJECT_ROOT, "data"))
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "api_usage.db")

# Google Gemini Official API Pricing Rates (per 1,000,000 tokens)
PRICING_CONFIG = {
    "gemini-3.8-flash": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
    "gemini-3.5-flash-lite": {"input": 0.075 / 1_000_000, "output": 0.30 / 1_000_000},
    "gemini-3-flash-preview": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
}
DEFAULT_RATES = PRICING_CONFIG["gemini-3.8-flash"]


def _get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db():
    """Create the api_usage_logs table and performance indexes."""
    with _get_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS api_usage_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_uid TEXT NOT NULL,
                user_email TEXT NOT NULL,
                is_verified INTEGER NOT NULL DEFAULT 1,
                feature TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                candidates_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                estimated_cost_usd REAL NOT NULL,
                latency_ms INTEGER,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_user_email ON api_usage_logs(user_email);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_created_at ON api_usage_logs(created_at);")


init_db()


def log_usage(
    uid: str,
    email: str,
    feature: str,
    model: str,
    prompt_tokens: int = 0,
    candidates_tokens: int = 0,
    latency_ms: Optional[int] = None,
    is_verified: bool = True
) -> float:
    """Log an LLM invocation and return estimated USD cost."""
    try:
        rates = PRICING_CONFIG.get(model, DEFAULT_RATES)
        prompt_tokens = prompt_tokens or 0
        candidates_tokens = candidates_tokens or 0
        total_tokens = prompt_tokens + candidates_tokens
        cost = (prompt_tokens * rates["input"]) + (candidates_tokens * rates["output"])

        with _get_connection() as conn:
            conn.execute(
                """
                INSERT INTO api_usage_logs
                (user_uid, user_email, is_verified, feature, model, prompt_tokens, candidates_tokens, total_tokens, estimated_cost_usd, latency_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid or "anonymous",
                    email or "unauthenticated",
                    1 if is_verified else 0,
                    feature,
                    model,
                    prompt_tokens,
                    candidates_tokens,
                    total_tokens,
                    cost,
                    latency_ms
                )
            )
        return cost
    except Exception as e:
        print(f"[UsageTracker] Error logging telemetry: {e}")
        return 0.0


def get_aggregated_usage() -> List[Dict[str, Any]]:
    """Return aggregated usage summary grouped by user (total requests, tokens, cost, last active)."""
    try:
        with _get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT 
                    user_uid as uid,
                    user_email as email,
                    COUNT(*) as total_requests,
                    SUM(total_tokens) as total_tokens,
                    SUM(estimated_cost_usd) as total_cost,
                    MAX(created_at) as last_active_at
                FROM api_usage_logs
                GROUP BY user_uid, user_email
                ORDER BY total_cost DESC
            """)
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[UsageTracker] Error fetching aggregated usage: {e}")
        return []


def get_recent_usage_logs(limit: int = 50) -> List[Dict[str, Any]]:
    """Return recent raw usage logs for audit inspection."""
    try:
        with _get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, user_uid, user_email, feature, model, prompt_tokens, candidates_tokens, total_tokens, estimated_cost_usd, latency_ms, created_at
                FROM api_usage_logs
                ORDER BY id DESC
                LIMIT ?
            """, (limit,))
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[UsageTracker] Error fetching recent logs: {e}")
        return []

