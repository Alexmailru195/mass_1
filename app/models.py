from sqlalchemy.orm import relationship
from .database import Base  # Импортируем только Base
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from datetime import datetime


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)  # Никнейм (уникальный)
    display_name = Column(String, nullable=True)  # Имя для отображения
    hashed_password = Column(String, nullable=False)
    bio = Column(Text, nullable=True)  # О себе
    avatar_url = Column(String, nullable=True)  # Ссылка на аватарку в MinIO

    created_at = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)

    # Связи
    messages_sent = relationship("Message", back_populates="sender", foreign_keys="Message.sender_id")
    chats = relationship("Chat", secondary="chat_participants", back_populates="participants")


class Chat(Base):
    __tablename__ = "chats"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=True)  # Название группы или Null для личного чата
    type = Column(String, default="private")  # 'private', 'group', 'channel'
    is_self_destructing = Column(Boolean, default=False)  # Чат с таймером жизни
    self_destruct_timer = Column(Integer, nullable=True)  # Время жизни сообщений в секундах (если > 0)

    participants = relationship("User", secondary="chat_participants", back_populates="chats")
    messages = relationship("Message", back_populates="chat", cascade="all, delete-orphan")


class ChatParticipant(Base):
    __tablename__ = "chat_participants"
    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    chat_id = Column(Integer, ForeignKey("chats.id"), primary_key=True)


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    text = Column(Text, nullable=True)
    file_url = Column(String, nullable=True)
    file_type = Column(String, nullable=True)

    sender_id = Column(Integer, ForeignKey("users.id"))
    chat_id = Column(Integer, ForeignKey("chats.id"))

    reply_to_id = Column(Integer, nullable=True)
    is_edited = Column(Boolean, default=False)
    edited_at = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # ВАЖНО: Явно установи default=False
    is_read = Column(Boolean, default=False)

    sender = relationship("User", back_populates="messages_sent")
    chat = relationship("Chat", back_populates="messages")