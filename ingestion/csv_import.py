"""
CSV ingestion: source-specific parsing -> normalized DataFrame -> source-agnostic insert.
A bank/broker API adapter would plug in at the same seam (produce the same normalized
DataFrame), so adding a new source never touches the DB layer.
"""
import hashlib
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from db.models import IngestionBatch, Transaction

REQUIRED_COLUMNS = {"txn_date", "account_id", "txn_type", "amount", "description"}


def _dedupe_hash(row: pd.Series) -> str:
    raw = f"{row['txn_date']}|{row['account_id']}|{row['amount']}|{row['description']}"
    return hashlib.sha256(raw.encode()).hexdigest()


def normalize_bank_csv(path: str, account_id: int) -> pd.DataFrame:
    """Adapter for a generic bank statement export: Date, Description, Debit, Credit columns."""
    raw = pd.read_csv(path)
    df = pd.DataFrame()
    df["txn_date"] = pd.to_datetime(raw["Date"]).dt.date
    df["account_id"] = account_id
    df["description"] = raw["Description"].astype(str)
    debit = raw.get("Debit", pd.Series([0] * len(raw))).fillna(0)
    credit = raw.get("Credit", pd.Series([0] * len(raw))).fillna(0)
    df["amount"] = credit - debit
    df["txn_type"] = df["amount"].apply(lambda a: "income" if a > 0 else "expense")
    df["ticker"] = None
    df["quantity"] = None
    df["price"] = None
    df["category_id"] = None
    return df


def validate(df: pd.DataFrame) -> list[str]:
    errors = []
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        errors.append(f"missing required columns: {missing}")
    if df.empty:
        errors.append("no rows to import")
    if "amount" in df.columns and df["amount"].isna().any():
        errors.append(f"{df['amount'].isna().sum()} rows have a null amount")
    return errors


def normalize_and_insert(session: Session, df: pd.DataFrame, source: str, filename: str = "") -> IngestionBatch:
    """Source-agnostic insert path: validates, dedupes against existing transactions,
    records an audit batch, inserts. Every source (CSV, Account Aggregator, broker API)
    funnels through this one function."""
    errors = validate(df)
    batch = IngestionBatch(source=source, filename=filename, row_count=len(df))

    if errors:
        batch.status = "failed"
        batch.error_log = "; ".join(errors)
        session.add(batch)
        session.commit()
        return batch

    df = df.copy()
    df["dedupe_hash"] = df.apply(_dedupe_hash, axis=1)

    existing_hashes = {h for (h,) in session.query(Transaction.dedupe_hash).all()}
    new_rows = df[~df["dedupe_hash"].isin(existing_hashes)]

    session.add(batch)
    session.flush()  # get batch.id

    for _, row in new_rows.iterrows():
        session.add(Transaction(
            account_id=int(row["account_id"]),
            txn_date=row["txn_date"],
            txn_type=row["txn_type"],
            ticker=row.get("ticker"),
            quantity=row.get("quantity"),
            price=row.get("price"),
            amount=float(row["amount"]),
            category_id=row.get("category_id"),
            description=row["description"],
            dedupe_hash=row["dedupe_hash"],
            batch_id=batch.id,
        ))

    batch.row_count = len(new_rows)
    batch.status = "success"
    session.commit()
    return batch
