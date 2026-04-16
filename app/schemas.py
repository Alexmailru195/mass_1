from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

# --- USERS ---
class UserCreate(BaseModel):
    username: str
    password: str
    display_name: Optional[str] = None
    bio: Optional[str] = None

class UserResponse(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    status: str  # 'online', 'offline', 'был ...'

    class Config:
        from_attributes = True

class UserSearchResponse(UserResponse):
    pass

# --- CHATS ---
class ChatCreate(BaseModel):
    name: Optional[str] = None
    type: str = "private"  # 'private' или 'group'
    participant_ids: List[int] # Список ID пользователей

class ChatResponse(BaseModel):
    id: int
    name: Optional[str] = None
    type: str
    participants: List[UserResponse] = [] # Можно упростить до List[int] если не нужны полные данные

    class Config:
        from_attributes = True

# --- MESSAGES (для WebSocket и API) ---
class MessageCreate(BaseModel):
    text: Optional[str] = None
    file_url: Optional[str] = None
    reply_to_id: Optional[int] = None