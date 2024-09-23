from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse
import yaml
import hashlib
import os
from src.global_settings import USERS_FILE
import streamlit as st
from pydantic import BaseModel
from llama_index.llms.openai import OpenAI
import openai
from src.index_builder import build_indexes
from src.ingest_pipeline import ingest_documents
from src.conversation_engine import initialize_chatbot, load_chat_store, chat_response
from llama_index.core import Settings
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],  # Danh sách các origins được phép
    allow_credentials=True,
    allow_methods=["*"],  # Cho phép tất cả các phương thức
    allow_headers=["*"],  # Cho phép tất cả các header
)

def load_users():
    if os.path.exists(USERS_FILE) and os.path.getsize(USERS_FILE) > 0:
        with open(USERS_FILE, 'r') as file:
            users = yaml.safe_load(file)
        return users
    else:
        return {"usernames": {}}

def save_users(users):
    with open(USERS_FILE, 'w') as file:
        yaml.safe_dump(users, file)

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

@app.post("/register/")
def register(username: str = Form(...), password: str = Form(...), confirm_password: str = Form(...), email: str = Form(...), name: str = Form(...), age: int = Form(...), gender: str = Form(...), job: str = Form(...), address: str = Form(...)):
    if password != confirm_password:
        raise HTTPException(statoscope=400, detail="Passwords do not match")
    users = load_users()
    if username in users['usernames']:
        raise HTTPException(status_code=400, detail="Username already exists")
    hashed_password = hash_password(password)
    users['usernames'][username] = {
        'email': email,
        'name': name,
        'age': age,
        'gender': gender,
        'job': job,
        'address': address,
        'password': hashed_password
    }
    save_users(users)
    return {"message": "User registered successfully"}

@app.post("/login/")
def login(username: str = Form(...), password: str = Form(...)):
    users = load_users()
    if username not in users['usernames']:
        raise HTTPException(status_code=404, detail="Username not found")
    stored_password = users['usernames'][username]['password']
    if hash_password(password) != stored_password:
        raise HTTPException(status_code=401, detail="Incorrect password")
    return {"message": f"Welcome {username}!"}

@app.post("/guest-login/")
def guest_login():
    return {
        "message": "Logged in as Guest",
        "username": "Guest",
        "info": "No personal information provided"
    }

# Chat message model
class ChatMessage(BaseModel):
    username: str
    message: str

# Chat endpoint
@app.post("/chat/")
async def chat_endpoint(chat_message: ChatMessage):
    
    # Load chat store and initialize the chatbot with user data
    chat_store = load_chat_store()
    username = chat_message.username
    
    # Here we assume `user_info` is loaded from the user’s session or database.
    users = load_users()
    if username not in users['usernames']:
        raise HTTPException(status_code=404, detail="Username not found")

    user_info = users['usernames'][username]
    
    # Initialize the chatbot with the user's chat store and info
    agent = initialize_chatbot(chat_store, username, user_info)
    
    try:
        text = chat_response(agent, chat_store, chat_message.message)
        return {"status": "ok", "text": text}
    except:
        return {"status": "false"}
    
# @app.get("/rag/")
# async def read_item( time: str, q: Optional[str] = None, source: Optional[str] = None):
#     if q:
#         print(time)
#         data = ra(q,time,source)
#         sources = []
#         for docs in data["source_documents"]:
#             sources.append(docs.to_json()["kwargs"])
#         res = {
#             "result" : data["answer"],
#             "source_documents":sources
#         }
#         return JSONResponse(content=jsonable_encoder(res))
#     return None