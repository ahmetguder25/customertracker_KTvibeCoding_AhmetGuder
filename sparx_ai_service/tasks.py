import os
import json
import time
import requests
import hashlib
import networkx as nx
import community as community_louvain
import fitz  # PyMuPDF
from huey import SqliteHuey
from langchain_text_splitters import RecursiveCharacterTextSplitter
from dotenv import load_dotenv
import rag_db
import numpy as np
from sklearn.cluster import KMeans
from sentence_transformers import SentenceTransformer

# Load environment variables from .env file
load_dotenv()

# Initialize Huey with a local SQLite database for the queue
huey_db_path = os.path.join(os.path.dirname(__file__), 'huey_queue.db')
huey = SqliteHuey('rag_tasks', filename=huey_db_path)

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip()
if OLLAMA_BASE_URL:
    OLLAMA_URL = OLLAMA_BASE_URL
    print(f"GraphRAG: Offloading heavy LLM tasks to remote NVIDIA server at {OLLAMA_URL}")
else:
    OLLAMA_URL = "http://localhost:11434"
    print("GraphRAG: Running in local mode using Mac Ollama")

LLM_MODEL = "Qwen/Qwen2.5-7B-Instruct"

def check_vllm_status():
    """Verify vLLM is running and the required model is loaded."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/v1/models", timeout=5)
        resp.raise_for_status()
        models = [m.get('id', 'unknown') for m in resp.json().get('data', [])]
        if LLM_MODEL not in models:
            return False, f"Model '{LLM_MODEL}' not found in vLLM. Found: {models}"
        return True, "OK"
    except requests.exceptions.RequestException as e:
        return False, f"vLLM server unreachable at {OLLAMA_URL}: {e}"

def query_vllm(prompt, system="You are a helpful assistant."):
    """Send a prompt to vLLM using the OpenAI Chat Completions API format."""
    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 4096
    }
    resp = requests.post(f"{OLLAMA_URL}/v1/chat/completions", json=payload, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return str(data)

@huey.task()
def process_chunking_task(document_id, filepath):
    """Background task to extract and chunk a document."""
    try:
        rag_db.upsert_task(document_id, 'Chunking', 'Processing', 'Initializing PDF extraction...', 0)
        rag_db.upsert_task(document_id, 'Mapping', 'Not Started', '', 0)
        
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Document file {filepath} not found.")

        # Extract text using PyMuPDF
        doc = fitz.open(filepath)
        total_pages = len(doc)
        full_text = ""
        
        for i, page in enumerate(doc):
            full_text += page.get_text() + "\n"
            pct = int((i / total_pages) * 40)
            if i % 5 == 0:
                rag_db.upsert_task(document_id, 'Chunking', 'Processing', f'Extracting text (Page {i+1}/{total_pages})...', pct)
        
        rag_db.upsert_task(document_id, 'Chunking', 'Processing', 'Splitting text into chunks...', 40)
        
        # Split text
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
        chunks = splitter.split_text(full_text)
        total_chunks = len(chunks)
        
        rag_db.clear_chunks(document_id)
        
        for i, chunk_text in enumerate(chunks):
            chunk_hash = hashlib.md5(chunk_text.encode('utf-8')).hexdigest()
            rag_db.save_chunk(document_id, chunk_hash, chunk_text)
            
            if i % 10 == 0:
                pct = 40 + int((i / total_chunks) * 60)
                rag_db.upsert_task(document_id, 'Chunking', 'Processing', f'Saving chunks ({i}/{total_chunks})...', pct)

        rag_db.upsert_task(document_id, 'Chunking', 'Completed', f'Successfully generated {total_chunks} chunks.', 100)
        
    except Exception as e:
        rag_db.upsert_task(document_id, 'Chunking', 'Failed', f'Error: {str(e)}', 0)


@huey.task()
def process_mapping_task(document_id):
    """Background task to extract nodes/edges and build Knowledge Graph."""
    try:
        rag_db.upsert_task(document_id, 'Mapping', 'Processing', 'Checking AI service status...', 0)
        
        ok, msg = check_vllm_status()
        if not ok:
            raise RuntimeError(msg)
            
        chunks = rag_db.get_chunks(document_id)
        if not chunks:
            raise ValueError("No chunks found. Please run Chunking first.")
            
        # Do not drop chunks anymore, but cap at 500 for safety
        if len(chunks) > 500:
            chunks = chunks[:500]
            
        total_chunks = len(chunks)
        rag_db.upsert_task(document_id, 'Mapping', 'Processing', f'Starting parallel extraction for {total_chunks} chunks...', 5)
        
        G = nx.Graph()
        
        system_prompt = """Sen profesyonel bir finansal veri çıkarma motorusun. Metindeki Varlıkları (Şirketler, Riskler, Metrikler, Konseptler) ve İlişkileri çıkar.
KESİNLİKLE VE SADECE aşağıdaki formata birebir uyan geçerli bir JSON objesi döndür, ekstra hiçbir açıklama veya markdown ekleme:
{
  "nodes": [{"id": "Düğüm Adı", "type": "Kategori"}],
  "edges": [{"source": "Düğüm A", "target": "Düğüm B", "relation": "İlişki Açıklaması"}]
}"""
        
        import concurrent.futures
        
        def process_single_chunk(chunk):
            prompt = f"Şu metinden grafik varlıklarını Türkçe olarak çıkar:\n\n{chunk['raw_text']}"
            local_sys_prompt = system_prompt
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    response_text = query_vllm(prompt, system=local_sys_prompt)
                    cleaned = response_text.strip()
                    if cleaned.startswith("```json"): cleaned = cleaned[7:]
                    if cleaned.startswith("```"): cleaned = cleaned[3:]
                    if cleaned.endswith("```"): cleaned = cleaned[:-3]
                    cleaned = cleaned.strip()
                    return json.loads(cleaned)
                except requests.exceptions.RequestException:
                    raise
                except json.JSONDecodeError:
                    if attempt == max_retries:
                        print(f"Failed to parse JSON for chunk {chunk.get('id', 'unknown')} after {max_retries} retries.")
                        return None
                    else:
                        local_sys_prompt += "\nÖNEMLİ HATA: Önceki cevabın geçerli bir JSON değildi. SADECE VE SADECE JSON DÖNDÜRMELİSİN."
            return None

        # Process all chunks with 20 parallel workers
        with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
            future_to_chunk = {executor.submit(process_single_chunk, chunk): chunk for chunk in chunks}
            
            completed = 0
            for future in concurrent.futures.as_completed(future_to_chunk):
                completed += 1
                pct_base = 10
                pct_range = 60
                rag_db.upsert_task(document_id, 'Mapping', 'Processing', f'Yapay zeka analiz ediyor ({completed}/{total_chunks})...', pct_base + int((completed/total_chunks)*pct_range))
                
                try:
                    data = future.result()
                    if data:
                        for node in data.get("nodes", []):
                            if not isinstance(node, dict): continue
                            node_id = node.get("id") or node.get("name")
                            if node_id:
                                G.add_node(node_id, type=node.get("type", "Unknown"))
                        for edge in data.get("edges", []):
                            if not isinstance(edge, dict): continue
                            src = edge.get("source")
                            tgt = edge.get("target")
                            rel = edge.get("relation", "ilgili")
                            if src and tgt:
                                G.add_edge(src, tgt, relation=rel)
                except requests.exceptions.RequestException as e:
                    rag_db.upsert_task(document_id, 'Mapping', 'Failed', f"Network Error: Unable to reach remote Ollama server", 0)
                    return
        
        rag_db.upsert_task(document_id, 'Mapping', 'Processing', 'Topluluk kümeleri tespit ediliyor...', 70)
        
        if len(G.nodes) == 0:
            raise ValueError("Graf oluşturmak için hiçbir varlık çıkarılamadı.")
            
        # Louvain Community Detection
        communities = community_louvain.best_partition(G)
        
        # Group nodes by community
        clusters = {}
        for node, comm_id in communities.items():
            clusters.setdefault(comm_id, []).append(node)
            
        rag_db.clear_summaries(document_id)
        total_clusters = len(clusters)
        
        rag_db.upsert_task(document_id, 'Mapping', 'Processing', f'{total_clusters} küme için özetler oluşturuluyor...', 80)
        
        summary_system = "Sen uzman bir finansal analistsin. Aşağıda birbirleriyle ilişkili olarak kümelenmiş işletme varlıklarını tek bir tutarlı paragraf halinde Türkçe özetle."
        for i, (comm_id, nodes) in enumerate(clusters.items()):
            subgraph = G.subgraph(nodes)
            edges_desc = "\n".join([f"{u} -> {v}: {d.get('relation', '')}" for u, v, d in subgraph.edges(data=True)])
            nodes_desc = ", ".join(nodes)
            
            summary_prompt = f"Varlıklar: {nodes_desc}\nİlişkiler:\n{edges_desc}\n\nBu varlıkların arasındaki ilişkileri açıklayan Türkçe bir özet çıkar."
            
            try:
                summary = query_vllm(summary_prompt, system=summary_system)
            except requests.exceptions.RequestException as e:
                rag_db.upsert_task(document_id, 'Mapping', 'Failed', f"Network Error: Unable to reach remote Ollama server", pct)
                return
                
            rag_db.save_summary(document_id, comm_id, summary)
            
            pct = 80 + int((i / total_clusters) * 20)
            rag_db.upsert_task(document_id, 'Mapping', 'Processing', f'Kümeler özetleniyor ({i+1}/{total_clusters})...', pct)
            
        # Save NetworkX graph to disk
        graphs_dir = os.path.join(os.path.dirname(__file__), 'graphs')
        os.makedirs(graphs_dir, exist_ok=True)
        nx.write_gml(G, os.path.join(graphs_dir, f"{document_id}.gml"))
            
        rag_db.upsert_task(document_id, 'Mapping', 'Completed', f'Grafik başarıyla oluşturuldu: {len(G.nodes)} düğüm ve {total_clusters} küme.', 100)
        
    except Exception as e:
        rag_db.upsert_task(document_id, 'Mapping', 'Failed', f'Hata: {str(e)}', 0)
