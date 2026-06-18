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
huey = SqliteHuey('rag_tasks', filename='huey_queue.db')

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "").strip()
if OLLAMA_BASE_URL:
    OLLAMA_URL = OLLAMA_BASE_URL
    print(f"GraphRAG: Offloading heavy LLM tasks to remote NVIDIA server at {OLLAMA_URL}")
else:
    OLLAMA_URL = "http://localhost:11434"
    print("GraphRAG: Running in local mode using Mac Ollama")

LLM_MODEL = "qwen3.5:9b"

def check_ollama_status():
    """Verify Ollama is running and the required model is loaded."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        resp.raise_for_status()
        models = [m['name'] for m in resp.json().get('models', [])]
        if LLM_MODEL not in models and f"{LLM_MODEL}:latest" not in models:
            return False, f"Model '{LLM_MODEL}' not found in Ollama."
        return True, "OK"
    except requests.exceptions.RequestException as e:
        return False, f"Network Error: Unable to reach Ollama server at {OLLAMA_URL} ({str(e)})"
    except Exception as e:
        return False, f"Ollama service unreachable: {str(e)}"

def query_ollama(prompt, system="You are a strict JSON extraction system."):
    """Helper to query local Ollama LLM."""
    payload = {
        "model": LLM_MODEL,
        "system": system,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1}
    }
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=600)
    resp.raise_for_status()
    return resp.json().get("response", "")

@huey.task()
def process_chunking_task(document_id, filepath):
    """Background task to extract and chunk a document."""
    try:
        rag_db.upsert_task(document_id, 'Chunking', 'Processing', 'Initializing PDF extraction...', 0)
        
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Document file {filepath} not found.")

        # Extract text using PyMuPDF
        doc = fitz.open(filepath)
        total_pages = len(doc)
        full_text = ""
        
        for i, page in enumerate(doc):
            full_text += page.get_text() + "\n"
            pct = int((i / total_pages) * 40)  # Extraction is 40% of the chunking task
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
        
        ok, msg = check_ollama_status()
        if not ok:
            raise RuntimeError(msg)
            
        chunks = rag_db.get_chunks(document_id)
        if not chunks:
            raise ValueError("No chunks found. Please run Chunking first.")
            
        total_chunks_original = len(chunks)
        rag_db.upsert_task(document_id, 'Mapping', 'Processing', f'Generating vectors for {total_chunks_original} chunks...', 5)
        
        # 1. Embed all chunks quickly on CPU
        embedder = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
        texts = [c['raw_text'] for c in chunks]
        embeddings = embedder.encode(texts, show_progress_bar=False)
        
        # 2. Cluster the chunks to find representative samples
        n_clusters = min(15, total_chunks_original)
        rag_db.upsert_task(document_id, 'Mapping', 'Processing', f'Clustering {total_chunks_original} chunks into {n_clusters} topics...', 10)
        
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init='auto')
        kmeans.fit(embeddings)
        
        # 3. Find the chunk closest to each cluster centroid
        representative_chunks = []
        for i in range(n_clusters):
            centroid = kmeans.cluster_centers_[i]
            # Calculate distance of all chunks in this cluster to the centroid
            cluster_indices = np.where(kmeans.labels_ == i)[0]
            cluster_embeddings = embeddings[cluster_indices]
            distances = np.linalg.norm(cluster_embeddings - centroid, axis=1)
            closest_index = cluster_indices[np.argmin(distances)]
            representative_chunks.append(chunks[closest_index])
            
        chunks = representative_chunks
        total_chunks = len(chunks)
        
        G = nx.Graph()
        
        system_prompt = """You are a financial entity extraction engine. Extract nodes (Companies, Risks, Metrics, Concepts) and edges (Relationships).
You MUST return ONLY a valid JSON object matching this schema, with no markdown formatting or conversational text:
{
  "nodes": [{"id": "Node Name", "type": "Category"}],
  "edges": [{"source": "Node A", "target": "Node B", "relation": "Description"}]
}"""
        
        for i, chunk in enumerate(chunks):
            pct_base = 10
            pct_range = 60
            rag_db.upsert_task(document_id, 'Mapping', 'Processing', f'AI extracting entities (Topic {i+1}/{total_chunks})...', pct_base + int((i/total_chunks)*pct_range))
            
            prompt = f"Extract graph entities from this text:\\n\\n{chunk['raw_text']}"
            
            # Auto-retry loop for bad JSON
            max_retries = 2
            for attempt in range(max_retries + 1):
                try:
                    response_text = query_ollama(prompt, system=system_prompt)
                    # Clean markdown code blocks if the model ignored instructions
                    cleaned = response_text.strip()
                    if cleaned.startswith("```json"): cleaned = cleaned[7:]
                    if cleaned.startswith("```"): cleaned = cleaned[3:]
                    if cleaned.endswith("```"): cleaned = cleaned[:-3]
                    cleaned = cleaned.strip()
                    
                    data = json.loads(cleaned)
                    
                    for node in data.get("nodes", []):
                        G.add_node(node["id"], type=node.get("type", "Unknown"))
                    for edge in data.get("edges", []):
                        G.add_edge(edge["source"], edge["target"], relation=edge.get("relation", ""))
                        
                    break # Success!
                except requests.exceptions.RequestException as e:
                    rag_db.upsert_task(document_id, 'Mapping', 'Failed', f"Network Error: Unable to reach remote Ollama server", 0)
                    return
                except json.JSONDecodeError:
                    if attempt == max_retries:
                        print(f"Failed to parse JSON for chunk {chunk['id']} after {max_retries} retries.")
                    else:
                        system_prompt += "\\nCRITICAL: You previously returned invalid JSON. YOU MUST RETURN ONLY RAW, PARSABLE JSON."
        
        rag_db.upsert_task(document_id, 'Mapping', 'Processing', 'Detecting community clusters...', 70)
        
        if len(G.nodes) == 0:
            raise ValueError("No entities extracted to form a graph.")
            
        # Louvain Community Detection
        # convert directed to undirected for louvain if necessary, nx.Graph is undirected by default
        communities = community_louvain.best_partition(G)
        
        # Group nodes by community
        clusters = {}
        for node, comm_id in communities.items():
            clusters.setdefault(comm_id, []).append(node)
            
        rag_db.clear_summaries(document_id)
        total_clusters = len(clusters)
        
        rag_db.upsert_task(document_id, 'Mapping', 'Processing', f'Generating summaries for {total_clusters} communities...', 80)
        
        summary_system = "You are a financial analyst. Summarize the following clustered business entities into a single cohesive paragraph explaining their relationships."
        for i, (comm_id, nodes) in enumerate(clusters.items()):
            subgraph = G.subgraph(nodes)
            edges_desc = "\\n".join([f"{u} -> {v}: {d.get('relation', '')}" for u, v, d in subgraph.edges(data=True)])
            nodes_desc = ", ".join(nodes)
            
            summary_prompt = f"Entities: {nodes_desc}\\nRelationships:\\n{edges_desc}\\n\\nGenerate a summary."
            pct = 80 + int((i / total_clusters) * 20)
            
            try:
                summary = query_ollama(summary_prompt, system=summary_system)
            except requests.exceptions.RequestException as e:
                rag_db.upsert_task(document_id, 'Mapping', 'Failed', f"Network Error: Unable to reach remote Ollama server", pct)
                return
                
            rag_db.save_summary(document_id, comm_id, summary)
            
            pct = 80 + int((i / total_clusters) * 20)
            rag_db.upsert_task(document_id, 'Mapping', 'Processing', f'Summarizing communities ({i+1}/{total_clusters})...', pct)
            
        # Save NetworkX graph to disk
        graphs_dir = os.path.join(os.path.dirname(__file__), 'static', 'graphs')
        os.makedirs(graphs_dir, exist_ok=True)
        nx.write_gml(G, os.path.join(graphs_dir, f"{document_id}.gml"))
            
        rag_db.upsert_task(document_id, 'Mapping', 'Completed', f'Graph built with {len(G.nodes)} nodes and {len(G.edges)} edges across {total_clusters} clusters.', 100)
        
    except Exception as e:
        rag_db.upsert_task(document_id, 'Mapping', 'Failed', f'Error: {str(e)}', 0)
