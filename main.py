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
import pandas as pd
import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
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

# Function to load data from JSON file
def load_scores(file: str, specific_username: str) -> pd.DataFrame:
    if os.path.exists(file) and os.path.getsize(file) > 0:
        with open(file, 'r') as f:
            data = json.load(f)
        # Filter data by specific username
        df = pd.DataFrame(data)
        new_df = df[df["username"] == specific_username]
        return new_df
    else:
        return pd.DataFrame(columns=["username", "Time", "Score", "Content", "Total guess"])

def score_to_numeric(score: str) -> int:
    score = score.lower()
    if score == "kém":
        return 1
    elif score == "trung bình":
        return 2
    elif score == "khá":
        return 3
    elif score == "tốt":
        return 4
    else:
        return 0  # Default case if none match

@app.get("/get_scores/{username}")
def get_scores(username: str, token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    verified_username = verify_token(token)
    if username != verified_username:
        raise HTTPException(status_code=403, detail="Unauthorized")
    df = load_scores(SCORES_FILE, username)
    if not df.empty:
        df["Time"] = pd.to_datetime(df["Time"])
        df["Score_num"] = df["Score"].apply(score_to_numeric)
        df["Score"] = df["Score"].str.lower()
        # Convert DataFrame to JSON serializable format
        data = df.to_dict(orient="records")
        return {"data": data}
    else:
        return {"data": []}

@app.get("/get_scores/{username}/recent")
def get_recent_scores(username: str, token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    verified_username = verify_token(token)
    if username != verified_username:
        raise HTTPException(status_code=403, detail="Unauthorized")
    df = load_scores(SCORES_FILE, username)
    if not df.empty:
        df["Time"] = pd.to_datetime(df["Time"])
        df["Score_num"] = df["Score"].apply(score_to_numeric)
        df["Score"] = df["Score"].str.lower()

        # Filter data for the last 7 days
        recent_date = df['Time'].max()
        start_date = recent_date - timedelta(days=6)
        df_filtered = df[(df['Time'] >= start_date) & (df['Time'] <= recent_date)]

        # Sort data by Time
        df_filtered = df_filtered.sort_values(by='Time')

        # Map 'Score' to colors
        color_map = {
            'kém': 'red',
            'trung bình': 'orange',
            'khá': 'yellow',
            'tốt': 'green'
        }
        df_filtered['color'] = df_filtered['Score'].map(color_map)
        
        # Convert DataFrame to JSON serializable format
        data = df_filtered.to_dict(orient="records")
        return {"data": data}
    else:
        return {"data": []}

@app.get("/get_scores/{username}/date/{date}")
def get_scores_by_date(username: str, date: str, token: str = Depends(oauth2_scheme)) -> Dict[str, Any]:
    verified_username = verify_token(token)
    if username != verified_username:
        raise HTTPException(status_code=403, detail="Unauthorized")
    df = load_scores(SCORES_FILE, username)
    if not df.empty:
        df["Time"] = pd.to_datetime(df["Time"])
        df["Score_num"] = df["Score"].apply(score_to_numeric)
        df["Score"] = df["Score"].str.lower()
        selected_date = pd.to_datetime(date)
        filtered_df = df[df["Time"].dt.date == selected_date.date()]
        data = filtered_df.to_dict(orient="records")
        return {"data": data}
    else:
        return {"data": []}

@app.get("/get_scores/{username}/plot_data")
def get_plot_data(username: str, token: str = Depends(oauth2_scheme)) -> Dict[str, List]:
    verified_username = verify_token(token)
    if username != verified_username:
        raise HTTPException(status_code=403, detail="Unauthorized")
    df = load_scores(SCORES_FILE, username)
    if not df.empty:
        df["Time"] = pd.to_datetime(df["Time"])
        df["Score_num"] = df["Score"].apply(score_to_numeric)
        df["Score"] = df["Score"].str.lower()
        
        # Filter data for the last 7 days
        recent_date = df['Time'].max()
        start_date = recent_date - timedelta(days=6)
        df_filtered = df[(df['Time'] >= start_date) & (df['Time'] <= recent_date)]
        
        # Sort data by Time
        df_filtered = df_filtered.sort_values(by='Time')
        
        # Map 'Score' to colors
        color_map = {
            'kém': 'red',
            'trung bình': 'orange',
            'khá': 'yellow',
            'tốt': 'green'
        }
        df_filtered['color'] = df_filtered['Score'].map(color_map)
        
        # Prepare data for plotting
        plot_data = {
            'x': df_filtered['Time'].dt.strftime('%Y-%m-%d %H:%M:%S').tolist(),
            'y': df_filtered['Score_num'].tolist(),
            'colors': df_filtered['color'].tolist(),
            'scores': df_filtered['Score'].tolist()
        }
        return plot_data
    else:
        return {}

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)