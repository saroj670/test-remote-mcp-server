import json
import os
import sqlite3
import tempfile
from datetime import datetime

import aiosqlite
from fastmcp import FastMCP


mcp = FastMCP(name="ExpenseTracker")


# Remote platforms may not allow writing inside the project folder.
# tempfile.gettempdir() usually gives a writable directory.
TEMP_DIR = tempfile.gettempdir()
DB_PATH = os.path.join(TEMP_DIR, "expenses.db")


CATEGORIES = [
    "Food & Dining",
    "Transportation",
    "Shopping",
    "Entertainment",
    "Bills & Utilities",
    "Healthcare",
    "Travel",
    "Education",
    "Business",
    "Other",
]


def init_db():
    """
    Initialize SQLite database.
    Safe to call multiple times.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    category TEXT NOT NULL,
                    subcategory TEXT DEFAULT '',
                    note TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

        print(f"Database initialized successfully at: {DB_PATH}")

    except Exception as exc:
        print(f"Database initialization error: {exc}")
        raise


def validate_amount(amount: float) -> float:
    """
    Validate amount before saving.
    """
    if amount <= 0:
        raise ValueError("Amount must be greater than 0.")

    return amount


def validate_category(category: str) -> str:
    """
    Validate expense category.
    """
    if not category:
        raise ValueError("Category is required.")

    category = category.strip()

    allowed_lower = {
        item.lower(): item
        for item in CATEGORIES
    }

    if category.lower() not in allowed_lower:
        raise ValueError(
            f"Invalid category '{category}'. "
            f"Allowed categories are: {', '.join(CATEGORIES)}"
        )

    return allowed_lower[category.lower()]


def normalize_date(date: str) -> str:
    """
    Validate date format.

    Expected format:
    YYYY-MM-DD
    """
    if not date:
        return datetime.now().strftime("%Y-%m-%d")

    try:
        parsed = datetime.strptime(date, "%Y-%m-%d")
        return parsed.strftime("%Y-%m-%d")

    except ValueError:
        raise ValueError(
            "Date must be in YYYY-MM-DD format."
        )


# Initialize database during startup
init_db()


@mcp.tool()
async def add_expense(
    date: str,
    amount: float,
    category: str,
    subcategory: str = "",
    note: str = "",
) -> dict:
    """
    Add a new expense entry.

    Use this when the user wants to record
    a spending transaction.

    Required:
    - date: YYYY-MM-DD
    - amount: expense amount
    - category: one of the allowed categories

    Example:
    add_expense(
        "2026-04-20",
        25,
        "Food & Dining",
        "Lunch",
        "Lunch at office",
    )
    """
    init_db()

    date = normalize_date(date)
    amount = validate_amount(amount)
    category = validate_category(category)
    subcategory = subcategory.strip() if subcategory else ""
    note = note.strip() if note else ""
    created_at = datetime.now().isoformat(
        timespec="seconds"
    )

    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """
                INSERT INTO expenses(
                    date,
                    amount,
                    category,
                    subcategory,
                    note,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    date,
                    amount,
                    category,
                    subcategory,
                    note,
                    created_at,
                ),
            )

            await conn.commit()

            return {
                "status": "success",
                "id": cursor.lastrowid,
                "message": "Expense added successfully.",
                "database_path": DB_PATH,
            }

    except Exception as exc:
        return {
            "status": "error",
            "message": (
                "Database error while adding expense: "
                f"{str(exc)}"
            ),
        }


@mcp.tool()
async def list_expenses(
    start_date: str,
    end_date: str,
) -> list[dict] | dict:
    """
    List expense entries within an inclusive date range.

    Example:
    list_expenses("2026-04-01", "2026-04-30")
    """
    init_db()

    start_date = normalize_date(start_date)
    end_date = normalize_date(end_date)

    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """
                SELECT
                    id,
                    date,
                    amount,
                    category,
                    subcategory,
                    note,
                    created_at
                FROM expenses
                WHERE date BETWEEN ? AND ?
                ORDER BY date DESC, id DESC
                """,
                (
                    start_date,
                    end_date,
                ),
            )

            rows = await cursor.fetchall()

            columns = [
                col[0]
                for col in cursor.description
            ]

            return [
                dict(zip(columns, row))
                for row in rows
            ]

    except Exception as exc:
        return {
            "status": "error",
            "message": (
                f"Error listing expenses: {str(exc)}"
            ),
        }


@mcp.tool()
async def summarize(
    start_date: str,
    end_date: str,
    category: str | None = None,
) -> list[dict] | dict:
    """
    Summarize expenses by category
    within an inclusive date range.

    Examples:

    summarize(
        "2026-04-01",
        "2026-04-30",
    )

    summarize(
        "2026-04-01",
        "2026-04-30",
        "Food & Dining",
    )
    """
    init_db()

    start_date = normalize_date(start_date)
    end_date = normalize_date(end_date)

    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            query = """
                SELECT
                    category,
                    SUM(amount) AS total_amount,
                    COUNT(*) AS count
                FROM expenses
                WHERE date BETWEEN ? AND ?
            """

            params = [
                start_date,
                end_date,
            ]

            if category:
                category = validate_category(category)

                query += " AND category = ?"
                params.append(category)

            query += """
                GROUP BY category
                ORDER BY total_amount DESC
            """

            cursor = await conn.execute(
                query,
                params,
            )

            rows = await cursor.fetchall()

            columns = [
                col[0]
                for col in cursor.description
            ]

            return [
                dict(zip(columns, row))
                for row in rows
            ]

    except Exception as exc:
        return {
            "status": "error",
            "message": (
                f"Error summarizing expenses: {str(exc)}"
            ),
        }


@mcp.tool()
async def delete_expense(
    expense_id: int,
) -> dict:
    """
    Delete an expense by ID.

    Use this only when the user clearly
    asks to delete an expense.
    """
    init_db()

    if expense_id <= 0:
        raise ValueError(
            "expense_id must be greater than 0."
        )

    try:
        async with aiosqlite.connect(DB_PATH) as conn:
            cursor = await conn.execute(
                """
                DELETE FROM expenses
                WHERE id = ?
                """,
                (expense_id,),
            )

            await conn.commit()

            if cursor.rowcount == 0:
                return {
                    "status": "not_found",
                    "message": (
                        f"No expense found with ID "
                        f"{expense_id}."
                    ),
                }

            return {
                "status": "success",
                "message": (
                    f"Expense {expense_id} "
                    "deleted successfully."
                ),
            }

    except Exception as exc:
        return {
            "status": "error",
            "message": (
                f"Error deleting expense: {str(exc)}"
            ),
        }


@mcp.tool()
def list_categories() -> list[str]:
    """
    List allowed expense categories.
    """
    return CATEGORIES


@mcp.tool()
def get_database_location() -> dict:
    """
    Show where the SQLite database is stored.

    Useful for debugging remote deployments.
    """
    init_db()

    return {
        "database_path": DB_PATH,
        "note": (
            "This path may be temporary in cloud deployments. "
            "Use PostgreSQL/MySQL for production persistence."
        ),
    }


@mcp.resource(
    "expense:///categories",
    mime_type="application/json",
)
def categories() -> str:
    """
    Return allowed categories as JSON resource.
    """
    return json.dumps(
        {
            "categories": CATEGORIES,
        },
        indent=2,
    )


if __name__ == "__main__":
    mcp.run(
        transport="http",
        host="0.0.0.0",
        port=8000,
    )