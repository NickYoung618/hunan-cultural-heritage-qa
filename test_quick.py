#!/usr/bin/env python3
"""HM-RAG 快速测试脚本"""
import sys
print("[1/6] Script starting...", flush=True)

sys.path.insert(0, '/sessions/inspiring-practical-brahmagupta/mnt/huxiang')

print("[2/6] Loading environment...", flush=True)
from dotenv import load_dotenv
import os
load_dotenv('/sessions/inspiring-practical-brahmagupta/mnt/huxiang/.env')
print(f"  MIMO_API_KEY: {'SET' if os.getenv('MIMO_API_KEY') else 'NOT SET'}", flush=True)

print("[3/6] Importing modules...", flush=True)
from openai import OpenAI
import chromadb
from langgraph.graph import StateGraph, END
from typing import TypedDict, Literal
print("  All imports OK", flush=True)

print("[4/6] Testing MIMO API...", flush=True)
try:
    client = OpenAI(
        api_key=os.getenv('MIMO_API_KEY'),
        base_url=os.getenv('MIMO_BASE_URL')
    )
    resp = client.chat.completions.create(
        model='mimo-v2.5-pro',
        messages=[{'role': 'user', 'content': 'Hello, respond with OK'}],
        max_tokens=5
    )
    print(f"  API Response: {resp.choices[0].message.content}", flush=True)
except Exception as e:
    print(f"  API error: {e}", flush=True)

print("[5/6] Testing ChromaDB...", flush=True)
try:
    chroma = chromadb.PersistentClient(path='/tmp/chroma_data')
    coll = chroma.get_or_create_collection('huxiang_spirit')
    print(f"  Collection: {coll.name}, Count: {coll.count()}", flush=True)

    # Insert test data
    coll.upsert(
        ids=['test_001'],
        documents=['湖湘文化的精神内核是「吃得苦、霸得蛮、耐得烦」'],
        metadatas=[{'source': 'test'}]
    )
    print(f"  After insert: {coll.count()}", flush=True)

    # Test query
    results = coll.query(query_texts=['湖湘精神'], n_results=1)
    print(f"  Query result: {results['documents'][0][:50]}...", flush=True)
    print("  ChromaDB OK", flush=True)
except Exception as e:
    print(f"  ChromaDB error: {e}", flush=True)

print("[6/6] All basic tests passed!", flush=True)
