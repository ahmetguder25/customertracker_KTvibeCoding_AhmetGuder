import os
import sys
import json
import time
import requests
import fitz  # PyMuPDF
import networkx as nx
import concurrent.futures
from langchain_text_splitters import RecursiveCharacterTextSplitter
import community as community_louvain
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

VLLM_URL = "http://localhost:8000/v1/chat/completions"
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

# Hard limit for chunks if the document is huge
MAX_CHUNKS = 1000

def check_vllm_status():
    try:
        r = requests.get("http://localhost:8000/v1/models", timeout=5)
        if r.status_code == 200:
            return True
        return False
    except Exception:
        return False

def query_vllm(prompt, system=""):
    payload = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,
        "max_tokens": 2048
    }
    resp = requests.post(VLLM_URL, json=payload, timeout=600)
    resp.raise_for_status()
    data = resp.json()
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        return str(data)

def extract_text(pdf_path):
    print(f"[*] Extracting text from {pdf_path}...")
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text() + "\n"
    return text

def chunk_text(text):
    print("[*] Splitting text into chunks...")
    splitter = RecursiveCharacterTextSplitter(chunk_size=600, chunk_overlap=100)
    chunks = splitter.split_text(text)
    if len(chunks) > MAX_CHUNKS:
        print(f"[*] Truncating from {len(chunks)} chunks to {MAX_CHUNKS} limit.")
        chunks = chunks[:MAX_CHUNKS]
    print(f"[*] Generated {len(chunks)} chunks.")
    return chunks

def process_single_chunk(chunk_text):
    system_prompt = """Sen profesyonel bir finansal veri çıkarma motorusun. Metindeki Varlıkları (Şirketler, Riskler, Metrikler, Konseptler) ve İlişkileri çıkar.
KESİNLİKLE VE SADECE aşağıdaki formata birebir uyan geçerli bir JSON objesi döndür, ekstra hiçbir açıklama veya markdown ekleme:
{
  "nodes": [{"id": "Düğüm Adı", "type": "Kategori"}],
  "edges": [{"source": "Düğüm A", "target": "Düğüm B", "relation": "İlişki Açıklaması"}]
}"""
    
    prompt = f"Şu metinden grafik varlıklarını Türkçe olarak çıkar:\n\n{chunk_text}"
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
        except requests.exceptions.RequestException as e:
            print(f"Network error: {e}")
            return None
        except json.JSONDecodeError:
            if attempt == max_retries:
                return None
            else:
                local_sys_prompt += "\nÖNEMLİ HATA: Önceki cevabın geçerli bir JSON değildi. SADECE VE SADECE JSON DÖNDÜRMELİSİN."
    return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python sparx_ai_linux.py <path_to_pdf>")
        sys.exit(1)
        
    pdf_path = sys.argv[1]
    if not os.path.exists(pdf_path):
        print(f"Error: File {pdf_path} not found.")
        sys.exit(1)
        
    if not check_vllm_status():
        print("Error: vLLM server is not running on http://localhost:8000")
        sys.exit(1)
        
    text = extract_text(pdf_path)
    chunks = chunk_text(text)
    
    G = nx.Graph()
    
    print("\n[*] Starting highly concurrent Knowledge Graph extraction (20 workers)...")
    # Using 20 parallel workers to hit vLLM with 20 simultaneous requests
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        future_to_chunk = {executor.submit(process_single_chunk, chunk): chunk for chunk in chunks}
        
        for future in tqdm(concurrent.futures.as_completed(future_to_chunk), total=len(chunks), desc="Processing Chunks"):
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
            except Exception as e:
                pass

    if len(G.nodes) == 0:
        print("\n[!] Error: No entities extracted. The graph is empty.")
        sys.exit(1)
        
    print(f"\n[*] Graph extraction complete! Nodes: {len(G.nodes)}, Edges: {len(G.edges)}")
    print("[*] Running Louvain Community Detection...")
    
    communities = community_louvain.best_partition(G)
    clusters = {}
    for node, comm_id in communities.items():
        clusters.setdefault(comm_id, []).append(node)
        
    total_clusters = len(clusters)
    print(f"[*] Detected {total_clusters} communities.")
    
    print("\n[*] Summarizing communities and generating embeddings...")
    # Load SentenceTransformer locally for embeddings (same model as the Mac app)
    embedder = SentenceTransformer("nomic-ai/nomic-embed-text", trust_remote_code=True)
    
    summary_system = "Sen uzman bir finansal analistsin. Aşağıda birbirleriyle ilişkili olarak kümelenmiş işletme varlıklarını tek bir tutarlı paragraf halinde Türkçe özetle."
    
    final_results = []
    
    # We can also do community summarization concurrently (e.g., 5 workers)
    def summarize_cluster(comm_id, nodes):
        subgraph = G.subgraph(nodes)
        edges_desc = "\n".join([f"{u} -> {v}: {d.get('relation', '')}" for u, v, d in subgraph.edges(data=True)])
        nodes_desc = ", ".join(nodes)
        
        summary_prompt = f"Varlıklar: {nodes_desc}\nİlişkiler:\n{edges_desc}\n\nBu varlıkların arasındaki ilişkileri açıklayan Türkçe bir özet çıkar."
        
        try:
            summary = query_vllm(summary_prompt, system=summary_system)
            emb = embedder.encode(summary).tolist()
            return {
                "community_id": comm_id,
                "summary_text": summary,
                "embedding": emb
            }
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as exec_sum:
        sum_futures = [exec_sum.submit(summarize_cluster, c_id, n) for c_id, n in clusters.items()]
        for f in tqdm(concurrent.futures.as_completed(sum_futures), total=total_clusters, desc="Summarizing"):
            res = f.result()
            if res:
                final_results.append(res)
                
    output_file = "graph_summaries_output.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(final_results, f, ensure_ascii=False, indent=2)
        
    print(f"\n[+] SUCCESS! Final summaries and embeddings saved to {output_file}")
    print("[+] You can now securely copy this JSON file back to your Mac.")

if __name__ == "__main__":
    main()
