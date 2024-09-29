import uvicorn  # Thêm uvicorn vào import

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import JSONResponse
import yaml
import hashlib
import os
from src.global_settings import USERS_FILE, SCORES_FILE
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
import pandas as pd
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
import plotly.graph_objects as go
from fastapi.responses import JSONResponse
from scores import load_scores, score_to_numeric

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

class RegisterRequest(BaseModel):
    username: str
    password: str
    confirm_password: str
    email: str
    name: str
    age: int
    gender: str
    job: str
    address: str

@app.post("/register/")
def register(registerRequest: RegisterRequest):
    password = registerRequest.password
    confirm_password = registerRequest.confirm_password
    if password != confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match")
    users = load_users()
    username = registerRequest.username
    if username in users['usernames']:
        raise HTTPException(status_code=400, detail="Username already exists")
    hashed_password = hash_password(password)
    users['usernames'][username] = {
        'email': registerRequest.email,
        'name': registerRequest.name,
        'age': registerRequest.age,
        'gender': registerRequest.gender,
        'job': registerRequest.job,
        'address': registerRequest.address,
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

@app.post("/chat/")
async def chat_endpoint(chat_message: ChatMessage, token: str = Depends(oauth2_scheme)):
    username = verify_token(token)
    
    # Load chat store and initialize the chatbot with user data
    chat_store = load_chat_store()

    # Initialize the chatbot
    users = load_users()
    if username not in users['usernames']:
        raise HTTPException(status_code=404, detail="Username not found")

    # Retrieve the user's information
    user_info = users['usernames'][username]

    # Reformat the user info as per the desired output format
    formatted_user_info = {
        'username': username,
        'address': user_info['address'],
        'age': user_info['age'],
        'email': user_info['email'],
        'gender': user_info['gender'],
        'job': user_info['job'],
        'name': user_info['name'],
        'password': user_info['password']
    }

    # Initialize the chatbot with the user's info
    agent = initialize_chatbot(chat_store, username, formatted_user_info)
    try:
        text = chat_response(agent, chat_store, chat_message.message)
        return {"status": "ok", "text": text, "user_info": formatted_user_info}
    except Exception as e:
        return {"status": "false", "error": str(e)}
    
@app.get("/scores/last7days/")
def get_user_scores_last7days(token: str = Depends(oauth2_scheme)):
    username = verify_token(token)
    df = load_scores(SCORES_FILE, username)
    if df.empty:
        raise HTTPException(status_code=404, detail="No data found for user")
    else:
        df['Time'] = pd.to_datetime(df['Time'])
        recent_date = df['Time'].max()
        start_date = recent_date - timedelta(days=6)
        df_filtered = df[(df['Time'] >= start_date) & (df['Time'] <= recent_date)]
        df_filtered = df_filtered.sort_values(by='Time')
        df_filtered['Score_num'] = df_filtered['Score'].apply(score_to_numeric)
        # Chuyển dữ liệu về dạng JSON serializable
        df_filtered['Time'] = df_filtered['Time'].dt.strftime('%Y-%m-%d')
        return df_filtered.to_dict(orient='records')

@app.get("/scores/bydate/")
def get_user_scores_by_date(date: str, token: str = Depends(oauth2_scheme)):
    username = verify_token(token)
    df = load_scores(SCORES_FILE, username)
    if df.empty:
        raise HTTPException(status_code=404, detail="No data found for user")
    else:
        df['Time'] = pd.to_datetime(df['Time'])
        selected_date = pd.to_datetime(date)
        filtered_df = df[df["Time"].dt.date == selected_date.date()]
        if filtered_df.empty:
            raise HTTPException(status_code=404, detail=f"No data for date {date}")
        else:
            filtered_df['Time'] = filtered_df['Time'].dt.strftime('%Y-%m-%d')
            return filtered_df.to_dict(orient='records')
        
@app.get("/scores/")
def get_user_scores(token: str = Depends(oauth2_scheme)):
    username = verify_token(token)
    df = load_scores(SCORES_FILE, username)
    if df.empty:
        raise HTTPException(status_code=404, detail="No data found for user")
    else:
        df['Time'] = pd.to_datetime(df['Time'])
        df['Time'] = df['Time'].dt.strftime('%Y-%m-%d')
        return df.to_dict(orient='records')


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)