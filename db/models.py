"""
SQLAlchemy ORM schema — the single source of truth for the DB structure.
Generates working DDL for SQLite (default, zero setup) or PostgreSQL (set DATABASE_URL).
"""
from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    account_type: Mapped[str] = mapped_column(String(30))  # brokerage | bank | credit_card | wallet | fd
    institution: Mapped[str] = mapped_column(String(120), default="")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    is_liquid: Mapped[bool] = mapped_column(Boolean, default=False)  # counts toward liquidity ratio
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    transactions: Mapped[list["Transaction"]] = relationship(back_populates="account")


class AssetMetadata(Base):
    __tablename__ = "asset_metadata"

    id: Mapped[int] = mapped_column(primary_key=True)
    ticker: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(150))
    asset_class: Mapped[str] = mapped_column(String(30))  # equity | debt | gold | real_estate | cash
    sector: Mapped[str] = mapped_column(String(60), default="")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    target_weight_pct: Mapped[float] = mapped_column(Numeric(5, 2), default=0)  # for drift calc


class ExpenseCategory(Base):
    __tablename__ = "expense_categories"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    parent_id: Mapped[Optional[int]] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    match_pattern: Mapped[str] = mapped_column(String(200), default="")  # regex on description, for auto-categorization
    is_essential: Mapped[bool] = mapped_column(Boolean, default=True)  # feeds emergency-fund monthly-expense calc


class Transaction(Base):
    """The single append-only ledger. Every money movement lives here — nothing else is a source of truth."""
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    txn_date: Mapped[date] = mapped_column(Date, index=True)
    txn_type: Mapped[str] = mapped_column(String(20))  # buy | sell | deposit | withdrawal | expense | income | dividend
    ticker: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)  # null for pure cash txns
    quantity: Mapped[Optional[float]] = mapped_column(Numeric(18, 6), nullable=True)
    price: Mapped[Optional[float]] = mapped_column(Numeric(18, 4), nullable=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2))  # signed: +inflow / -outflow
    category_id: Mapped[Optional[int]] = mapped_column(ForeignKey("expense_categories.id"), nullable=True)
    description: Mapped[str] = mapped_column(Text, default="")
    dedupe_hash: Mapped[str] = mapped_column(String(64), index=True)  # date+account+amount+description hash
    batch_id: Mapped[Optional[int]] = mapped_column(ForeignKey("ingestion_batches.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    account: Mapped["Account"] = relationship(back_populates="transactions")
    category: Mapped[Optional["ExpenseCategory"]] = relationship()

    __table_args__ = (UniqueConstraint("dedupe_hash", name="uq_txn_dedupe"),)


class PortfolioSnapshot(Base):
    """Nightly materialized EOD holding value. Rebuilt from transactions + prices; powers TWR/IRR/drift
    without replaying full transaction history on every dashboard load."""
    __tablename__ = "portfolio_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    ticker: Mapped[str] = mapped_column(String(30))
    quantity: Mapped[float] = mapped_column(Numeric(18, 6))
    price: Mapped[float] = mapped_column(Numeric(18, 4))
    market_value: Mapped[float] = mapped_column(Numeric(18, 2))

    __table_args__ = (UniqueConstraint("snapshot_date", "account_id", "ticker", name="uq_snapshot"),)


class BenchmarkPrice(Base):
    __tablename__ = "benchmark_prices"

    id: Mapped[int] = mapped_column(primary_key=True)
    benchmark: Mapped[str] = mapped_column(String(30))  # e.g. NIFTY50
    price_date: Mapped[date] = mapped_column(Date, index=True)
    close: Mapped[float] = mapped_column(Numeric(18, 4))

    __table_args__ = (UniqueConstraint("benchmark", "price_date", name="uq_benchmark_price"),)


class Budget(Base):
    """Per-category monthly target, versioned by month so history isn't overwritten."""
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int] = mapped_column(ForeignKey("expense_categories.id"))
    month: Mapped[date] = mapped_column(Date)  # always day=1
    target_amount: Mapped[float] = mapped_column(Numeric(18, 2))

    __table_args__ = (UniqueConstraint("category_id", "month", name="uq_budget_month"),)


class IngestionBatch(Base):
    """Audit trail for every import — lets a bad CSV/API pull be identified and rolled back cleanly."""
    __tablename__ = "ingestion_batches"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(50))  # csv | account_aggregator | broker_api
    filename: Mapped[str] = mapped_column(String(200), default="")
    row_count: Mapped[int] = mapped_column(default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending | success | failed
    error_log: Mapped[str] = mapped_column(Text, default="")
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
