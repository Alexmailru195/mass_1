from fastapi import FastAPI, Depends, HTTPException, status, WebSocket, WebSocketDisconnect, UploadFile, File, Request, \
    Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
import json, asyncio, os, threading
from uuid import uuid4

from . import models, schemas, database, security, redis_client, s3_client, es_client

app = FastAPI(title="Messenger API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.post("/register", response_model=schemas.UserResponse)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = db.query(models.User).filter(models.User.username == user.username).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Username already registered")
    hashed_password = security.get_password_hash(user.password)
    new_user = models.User(
        username=user.username,
        hashed_password=hashed_password,
        display_name=user.display_name,
        bio=user.bio
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return {
        "id": new_user.id, "username": new_user.username,
        "display_name": new_user.display_name, "avatar_url": new_user.avatar_url,
        "bio": new_user.bio, "status": "offline"
    }


@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.username == form_data.username).first()
    if not user or not security.verify_password(form_data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    access_token_expires = timedelta(minutes=30)
    access_token = security.create_access_token(data={"sub": user.username}, expires_delta=access_token_expires)
    return {"access_token": access_token, "token_type": "bearer"}


@app.get("/users/search", response_model=List[schemas.UserSearchResponse])
def search_users(query: str, db: Session = Depends(get_db)):
    users = db.query(models.User).filter(
        (models.User.username.ilike(f"%{query}%")) |
        (models.User.display_name.ilike(f"%{query}%"))
    ).limit(10).all()
    result = []
    for user in users:
        status_text = redis_client.get_status(user.id)
        result.append({
            "id": user.id, "username": user.username,
            "display_name": user.display_name, "avatar_url": user.avatar_url,
            "bio": user.bio, "status": status_text
        })
    return result


@app.post("/users/{user_id}/status")
def update_status_endpoint(user_id: int):
    redis_client.update_status(user_id)
    return {"status": "updated"}


@app.post("/chats/", response_model=schemas.ChatResponse)
def create_chat(chat_data: schemas.ChatCreate, current_user_id: int, db: Session = Depends(get_db)):
    if chat_data.type == "private" and len(chat_data.participant_ids) == 2:
        existing_chat = db.query(models.Chat).join(models.ChatParticipant).filter(
            models.ChatParticipant.user_id.in_(chat_data.participant_ids)
        ).group_by(models.Chat.id).having(
            database.func.count(models.ChatParticipant.user_id) == 2
        ).first()
        if existing_chat:
            return existing_chat
    new_chat = models.Chat(name=chat_data.name, type=chat_data.type)
    db.add(new_chat)
    db.flush()
    for p_id in chat_data.participant_ids:
        participant = models.ChatParticipant(user_id=p_id, chat_id=new_chat.id)
        db.add(participant)
    db.commit()
    db.refresh(new_chat)
    return new_chat


@app.get("/chats/{user_id}")
def get_user_chats(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User not found")
    return user.chats


@app.put("/messages/{message_id}")
def edit_message(message_id: int, new_text: str, user_id: int, db: Session = Depends(get_db)):
    msg = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not msg: raise HTTPException(404, "Message not found")
    if msg.sender_id != user_id: raise HTTPException(403, "Not allowed")
    msg.text = new_text
    msg.is_edited = True
    msg.edited_at = datetime.utcnow()
    db.commit()
    return msg


@app.delete("/messages/{message_id}")
def delete_message(message_id: int, user_id: int, delete_for_all: bool = False, db: Session = Depends(get_db)):
    msg = db.query(models.Message).filter(models.Message.id == message_id).first()
    if not msg: raise HTTPException(404, "Message not found")
    if delete_for_all:
        if msg.sender_id != user_id: raise HTTPException(403, "Only author can delete for everyone")
        db.delete(msg)
    db.commit()
    return {"status": "deleted"}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    file_extension = file.filename.split(".")[-1] if "." in file.filename else "bin"
    unique_filename = f"{uuid4()}.{file_extension}"
    content = await file.read()
    file_url = s3_client.upload_file(content, unique_filename)
    if not file_url: raise HTTPException(status_code=500, detail="Failed to upload")
    file_type = "image" if file_extension.lower() in ['png', 'jpg', 'jpeg', 'webp'] else "document"
    if file_extension.lower() in ['mp4', 'mov', 'avi']: file_type = "video"
    return {"file_url": file_url, "file_type": file_type}


@app.websocket("/ws/{chat_id}")
async def websocket_endpoint(websocket: WebSocket, chat_id: int):
    await websocket.accept()
    db = database.SessionLocal()

    # Простая реализация без сложного threading/executor для начала,
    # чтобы убедиться, что соединение держится.
    # Для продакшена лучше использовать aioredis, но пока попробуем так.

    pubsub = redis_client.client.pubsub()
    pubsub.subscribe(f"chat_{chat_id}")

    stop_listening = asyncio.Event()

    async def listen_for_messages():
        try:
            while not stop_listening.is_set():
                # Используем asyncio.to_thread (Python 3.9+) или run_in_executor
                # Но сначала проверим, работает ли вообще подключение
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message['type'] == 'message':
                    data = json.loads(message['data'])
                    await websocket.send_json(data)
                # Небольшая пауза, чтобы не грузить CPU
                await asyncio.sleep(0.1)
        except Exception as e:
            print(f"Redis Listener Error: {e}")
        finally:
            pubsub.unsubscribe(f"chat_{chat_id}")
            pubsub.close()

    # Запускаем слушатель
    listener_task = asyncio.create_task(listen_for_messages())

    try:
        # 1. История
        messages = db.query(models.Message).filter(models.Message.chat_id == chat_id).order_by(
            models.Message.id.asc()).all()

        for msg in messages:
            sender_name = msg.sender.username if msg.sender else "Unknown"
            reply_text = ""
            if msg.reply_to_id:
                reply_msg = db.query(models.Message).filter(models.Message.id == msg.reply_to_id).first()
                if reply_msg: reply_text = reply_msg.text or "Медиафайл"

            await websocket.send_json({
                "type": "message", "id": msg.id, "text": msg.text,
                "file_url": msg.file_url, "sender": sender_name,
                "sender_id": msg.sender_id, "time": msg.timestamp.strftime("%H:%M"),
                "reply_to_id": msg.reply_to_id, "reply_text": reply_text,
                "is_edited": msg.is_edited, "is_read": msg.is_read
            })

        # 2. Прием сообщений
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type")
            sender_name = data.get("sender")

            if msg_type == "read_receipt":
                message_ids = data.get("message_ids", [])
                r_chat_id = data.get("chat_id")
                if message_ids and r_chat_id:
                    db.query(models.Message).filter(
                        models.Message.id.in_(message_ids),
                        models.Message.chat_id == r_chat_id
                    ).update({models.Message.is_read: True}, synchronize_session=False)
                    db.commit()
                    receipt_packet = {"type": "read_receipt", "sender": sender_name, "message_ids": message_ids,
                                      "chat_id": r_chat_id}
                    redis_client.publish(f"chat_{r_chat_id}", receipt_packet)
                continue

            if sender_name:
                sender_user = db.query(models.User).filter(models.User.username == sender_name).first()
                if sender_user: redis_client.update_status(sender_user.id)

            if msg_type == "message":
                text = data.get("text")
                file_url = data.get("file_url")
                reply_to_id = data.get("reply_to_id")

                sender_user = db.query(models.User).filter(models.User.username == sender_name).first()
                sender_id = sender_user.id if sender_user else None

                new_msg = models.Message(
                    text=text, file_url=file_url, sender_id=sender_id,
                    chat_id=chat_id, reply_to_id=reply_to_id,
                    timestamp=datetime.utcnow(), is_read=False
                )
                db.add(new_msg)
                db.commit()
                db.refresh(new_msg)

                reply_text = ""
                if reply_to_id:
                    original_msg = db.query(models.Message).filter(models.Message.id == reply_to_id).first()
                    if original_msg: reply_text = original_msg.text or "Медиафайл"

                msg_packet = {
                    "type": "message", "id": new_msg.id, "text": text,
                    "file_url": file_url, "sender": sender_name,
                    "sender_id": sender_id, "time": new_msg.timestamp.strftime("%H:%M"),
                    "reply_to_id": reply_to_id, "reply_text": reply_text,
                    "is_edited": False, "is_read": False
                }

                redis_client.publish(f"chat_{chat_id}", msg_packet)
                print(f"✅ Msg {new_msg.id} sent")

            elif msg_type == "typing":
                redis_client.publish(f"chat_{chat_id}", {"type": "typing", "sender": sender_name})
            elif msg_type == "reaction":
                redis_client.publish(f"chat_{chat_id}",
                                     {"type": "reaction_update", "msg_id": data.get("msg_id"), "sender": sender_name,
                                      "emoji": data.get("emoji")})

    except WebSocketDisconnect:
        print("Client disconnected")
    except Exception as e:
        import traceback
        print(f"❌ WS CRITICAL ERROR: {e}")
        traceback.print_exc()
    finally:
        stop_listening.set()
        if listener_task:
            listener_task.cancel()
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
        db.close()


@app.on_event("startup")
def startup():
    database.init_db()
    s3_client.init_bucket()
    try:
        es_client.init_index()
    except Exception as e:
        print(f"ES Error: {e}")


@app.post("/chats/list")
def get_chats_list(request_data: dict = Body(...), db: Session = Depends(get_db)):
    username = request_data.get("my_username")
    user_id = request_data.get("user_id")
    user = None
    if user_id:
        user = db.query(models.User).filter(models.User.id == user_id).first()
    elif username:
        user = db.query(models.User).filter(models.User.username == username).first()
    if not user: return []

    result = []
    for chat in user.chats:
        if chat.type == "private":
            partner = next((u for u in chat.participants if u.id != user.id), None)
            name = partner.username if partner else "Unknown"
        else:
            name = chat.name or "Group Chat"
        result.append({"chat_id": chat.id, "partner_name": name, "type": chat.type, "last_message": ""})
    return result


@app.post("/chats/start")
def start_chat(request_data: dict = Body(...), db: Session = Depends(get_db)):
    my_username = request_data.get("my_username")
    partner_username = request_data.get("partner_username")
    user1 = db.query(models.User).filter(models.User.username == my_username).first()
    user2 = db.query(models.User).filter(models.User.username == partner_username).first()
    if not user1 or not user2: raise HTTPException(status_code=404, detail="User not found")

    existing_chat = None
    for chat in user1.chats:
        if chat.type == "private" and user2 in chat.participants:
            existing_chat = chat
            break
    if existing_chat: return {"chat_id": existing_chat.id}

    new_chat = models.Chat(type="private", participants=[user1, user2])
    db.add(new_chat)
    db.commit()
    db.refresh(new_chat)
    return {"chat_id": new_chat.id}