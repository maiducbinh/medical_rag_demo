import uvicorn  # Thêm uvicorn vào import

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
from login_auth import timedelta, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES, verify_token
from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

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
    
    # Tạo token JWT
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(data={"sub": username}, expires_delta=access_token_expires)
    
    return {"access_token": access_token, "token_type": "bearer"}



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
    
@app.post("/chat1/")
async def chat_endpoint(chat_message: ChatMessage, token: str = Depends(oauth2_scheme)):
    username = verify_token(token)
    
    # Load chat store and initialize the chatbot with user data
    chat_store = load_chat_store()

    # Initialize the chatbot
    users = load_users()
    if username not in users['usernames']:
        raise HTTPException(status_code=404, detail="Username not found")

    user_info = users['usernames'][username]
    agent = initialize_chatbot(chat_store, username, user_info)
    
    try:
        text = chat_response(agent, chat_store, chat_message.message)
        return {"status": "ok", "text": text}
    except:
        return {"status": "false"}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)