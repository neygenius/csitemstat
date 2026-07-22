from sqlalchemy import Column, BigInteger, Integer, Text, Numeric, Boolean, TIMESTAMP, Date, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import BYTEA
from app.db.base import Base
import datetime

class User(Base):
    __tablename__ = "users"
    id = Column(BigInteger, primary_key=True)
    chat_id = Column(BigInteger, nullable=False)
    steam_id64 = Column(BYTEA, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    tracked_items = relationship("UserTrackedItem", back_populates="user")
    subscriptions = relationship("Subscription", back_populates="user")
    price_alerts = relationship("PriceAlert", back_populates="user")

class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, autoincrement=True)
    app_id = Column(Integer, nullable=False)
    market_hash_name = Column(Text, nullable=False)
    name = Column(Text, nullable=True)
    icon_url = Column(Text, nullable=True)
    is_tracked = Column(Boolean, default=False)
    __table_args__ = (UniqueConstraint('app_id', 'market_hash_name', name='uq_app_market'),)

    tracked_by = relationship("UserTrackedItem", back_populates="item")
    daily_stats = relationship("ItemDailyStats", back_populates="item")
    snapshot = relationship("ItemSnapshot", back_populates="item", uselist=False)
    subscriptions = relationship("Subscription", back_populates="item")
    price_alerts = relationship("PriceAlert", back_populates="item")

class UserTrackedItem(Base):
    __tablename__ = "user_tracked_items"
    user_id = Column(BigInteger, ForeignKey("users.id"), primary_key=True)
    item_id = Column(Integer, ForeignKey("items.id"), primary_key=True)
    added_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    user = relationship("User", back_populates="tracked_items")
    item = relationship("Item", back_populates="tracked_by")

class ItemDailyStats(Base):
    __tablename__ = "item_daily_stats"
    item_id = Column(Integer, ForeignKey("items.id"), primary_key=True)
    date = Column(Date, primary_key=True)
    price = Column(Numeric(10,2), nullable=False)
    volume = Column(Integer, nullable=False)

    item = relationship("Item", back_populates="daily_stats")

class ItemSnapshot(Base):
    __tablename__ = "item_snapshot"
    item_id = Column(Integer, ForeignKey("items.id"), primary_key=True)
    lowest_price = Column(Numeric(10,2), nullable=True)
    median_price = Column(Numeric(10,2), nullable=True)
    volume_24h = Column(Integer, nullable=True)
    price_24h_ago = Column(Numeric(10,2), nullable=True)
    trend_slope = Column(Numeric(10,6), nullable=True)
    trend_direction = Column(Text, nullable=True)
    updated_at = Column(TIMESTAMP(timezone=True))

    item = relationship("Item", back_populates="snapshot")

class Subscription(Base):
    __tablename__ = "subscriptions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    frequency = Column(Text, nullable=False)  # daily, weekly
    active = Column(Boolean, default=True)
    last_sent_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))
    __table_args__ = (UniqueConstraint('user_id', 'item_id', 'frequency', name='uq_subscription'),)

    user = relationship("User", back_populates="subscriptions")
    item = relationship("Item", back_populates="subscriptions")

class PriceAlert(Base):
    __tablename__ = "price_alerts"
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey("users.id"), nullable=False)
    item_id = Column(Integer, ForeignKey("items.id"), nullable=False)
    percent_change = Column(Numeric(5,2), nullable=False)
    period = Column(Text, nullable=False)
    active = Column(Boolean, default=True)
    last_triggered_at = Column(TIMESTAMP(timezone=True), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), default=lambda: datetime.datetime.now(datetime.timezone.utc))

    user = relationship("User", back_populates="price_alerts")
    item = relationship("Item", back_populates="price_alerts")