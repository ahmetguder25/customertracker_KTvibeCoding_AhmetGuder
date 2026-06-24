from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse
import os
import shutil
import uuid
from typing import Optional

# Setup directories
UPLOAD_DIR = "/tmp/sparx_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = FastAPI(title="Sparx AI Microservice")

import rag_db
import tasks

@app.post("/api/chunk")
async def chunk_document(document_id: str = Form(...), file: UploadFile = File(...)):
    if not document_id:
        raise HTTPException(status_code=400, detail="Missing document_id")
        
    filepath = os.path.join(UPLOAD_DIR, f"{document_id}_{file.filename}")
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    rag_db.upsert_task(document_id, "Chunking", "Pending", "Added to Sparx queue...")
    tasks.process_chunking_task(document_id, filepath)
    
    return {"message": "Chunking task dispatched", "document_id": document_id}

@app.post("/api/map")
async def map_document(document_id: str = Form(...)):
    if not document_id:
        raise HTTPException(status_code=400, detail="Missing document_id")
        
    rag_db.upsert_task(document_id, "Mapping", "Pending", "Added to Sparx queue...")
    tasks.process_mapping_task(document_id)
    
    return {"message": "Mapping task dispatched", "document_id": document_id}

@app.get("/api/status")
async def get_status(document_id: str):
    if not document_id:
        raise HTTPException(status_code=400, detail="Missing document_id")
        
    task_list = rag_db.get_task_status(document_id)
    status_map = {
        "chunking": {"status": "Not Started", "message": "", "percent": 0},
        "mapping": {"status": "Not Started", "message": "", "percent": 0}
    }
    for t in task_list:
        task_type = t["task_type"].lower()
        if task_type in status_map:
            status_map[task_type] = {
                "status": t["status"],
                "message": t["progress_message"],
                "percent": t["percent_complete"]
            }
    return status_map

@app.post("/api/analyze")
async def analyze_document(document_id: str = Form(...), query: str = Form(...)):
    try:
        ok, msg = tasks.check_vllm_status()
        if not ok:
            raise HTTPException(status_code=500, detail=msg)
            
        summaries = rag_db.get_summaries(document_id)
        if not summaries:
            raise HTTPException(status_code=400, detail="No graph summaries found for this document. Have you run Mapping?")
            
        import json
        import numpy as np
        query_emb = tasks.embedder.encode(query)
        scored_summaries = []
        for s in summaries:
            if s.get("embedding"):
                try:
                    s_emb = np.array(json.loads(s["embedding"]))
                    score = np.dot(query_emb, s_emb) / (np.linalg.norm(query_emb) * np.linalg.norm(s_emb))
                    scored_summaries.append((score, s["summary_text"]))
                except Exception:
                    pass
                    
        scored_summaries.sort(key=lambda x: x[0], reverse=True)
        top_summaries = [s[1] for s in scored_summaries[:15]]
        
        if not top_summaries:
            top_summaries = [s["summary_text"] for s in summaries[:15]]
            
        context = "\n\n".join(top_summaries)
        prompt = f"Aşağıdaki finansal grafik topluluk özetlerini dikkate alarak:\n\n{context}\n\nŞu soruyu cevapla: {query}"
        system = "Sen uzman bir finansal analistsin. Verilen bağlamı sentezleyerek soruyu doğru, detaylı ve profesyonel bir Türkçe rapor olarak cevapla."
        
        response = tasks.query_vllm(prompt, system=system)
        return {"answer": response, "document_id": document_id, "query": query}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
