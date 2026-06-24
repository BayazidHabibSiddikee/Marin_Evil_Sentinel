#!/bin/bash
# Start the RAG server in the background
python3 rag_server.py &
RAG_PID=$!

trap "kill $RAG_PID; exit" SIGTERM SIGINT

# Start the FastAPI web server
python3 main.py
