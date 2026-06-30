import os
import time
import requests
import fitz  # PyMuPDF
import ollama
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from huey import SqliteHuey
from microservices.crawler_service import crawler_db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMP_DIR = os.path.join(BASE_DIR, "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

CHATBOT_API_URL = "http://127.0.0.1:5001/api"
LLM_MODEL = "gemma3:27b"

import re
import unicodedata
import threading
from urllib.parse import urlparse

def slugify(text):
    text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
    text = re.sub(r'[^\w\s-]', '', text).strip().lower()
    text = re.sub(r'[-\s]+', '_', text)
    return text[:50] # Limit length

def crawl_task_sync(job_id):
    conn = crawler_db.get_db()
    # using dict row factory inside get_db so job can use dict keys
    row = conn.execute("SELECT * FROM crawler_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not row: return
    job = dict(row)

    try:
        max_depth = job.get("crawl_depth") or 0
        file_types = [t.strip().lower() for t in (job.get("file_types") or ".pdf").split(",") if t.strip()]
        target_url = job["target_url"]
        search_query = (job.get("search_query") or "").lower()
        
        parsed_target = urlparse(target_url)
        target_base = f"{parsed_target.scheme}://{parsed_target.netloc}"
        
        queue = [(target_url, 0)]
        visited_pages = set()
        found_files = [] # list of {"url": url, "text": link_text, "ext": ext}
        
        crawler_db.update_job_status(job_id, "Running", "Discovering files and sub-pages...")
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        while queue:
            current_url, depth = queue.pop(0)
            if current_url in visited_pages:
                continue
            visited_pages.add(current_url)
            
            try:
                resp = requests.get(current_url, headers=headers, timeout=10)
                if resp.status_code != 200: continue
                soup = BeautifulSoup(resp.text, 'html.parser')
                
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    
                    # Fix malformed 'href:' prefix seen on kgk.gov.tr
                    if href.startswith('href:'):
                        href = href[5:]
                        if not href.startswith('/') and not href.startswith('http'):
                            href = '/' + href
                            
                    full_link = urljoin(current_url, href)
                    link_text = a.get_text(strip=True)
                    
                    # Check if it's a target file
                    is_file = False
                    for ext in file_types:
                        if full_link.lower().split('?')[0].endswith(ext):
                            is_file = True
                            if not search_query or search_query in full_link.lower() or search_query in link_text.lower():
                                # Add to found files (deduplicate)
                                if not any(f['url'] == full_link for f in found_files):
                                    found_files.append({"url": full_link, "text": link_text, "ext": ext})
                            break
                    
                    # Check if it's a sub-page to crawl
                    if not is_file and depth < max_depth:
                        # only follow links within the target_url base
                        if full_link.startswith(target_url) and full_link not in visited_pages:
                            queue.append((full_link, depth + 1))
                            
            except Exception:
                pass
                
        if not found_files:
            crawler_db.update_job_status(job_id, "Idle", f"No matching files found. Checked {len(visited_pages)} pages.")
            return
            
        crawler_db.update_job_status(job_id, "Running", f"Found {len(found_files)} files. Processing...")
        
        processed_count = 0
        for f_data in found_files:
            processed_count += 1
            f_url = f_data["url"]
            f_ext = f_data["ext"]
            f_text = f_data["text"] or os.path.basename(urlparse(f_url).path)
            
            slug = slugify(f_text)
            if not slug: slug = "document"
            
            crawler_db.update_job_status(job_id, "Running", f"[{processed_count}/{len(found_files)}] Downloading {slug}...")
            
            try:
                f_resp = requests.get(f_url, headers=headers, timeout=30)
                f_resp.raise_for_status()
                
                temp_path = os.path.join(TEMP_DIR, f"temp_{job_id}{f_ext}")
                with open(temp_path, 'wb') as f:
                    f.write(f_resp.content)
                    
                date_digits = "00000000"
                if f_ext == ".pdf":
                    try:
                        doc = fitz.open(temp_path)
                        num_pages = len(doc)
                        start_page = max(0, num_pages - 5)
                        text_content = ""
                        for i in range(start_page, num_pages):
                            text_content += doc.load_page(i).get_text()
                        doc.close()
                        
                        prompt = f"Extract the most recent update date or publish date from the following text (which is from the end of a regulatory document).\nYour response MUST be ONLY the date formatted as YYYYMMDD. For example: 20251203\nIf you absolutely cannot find any date, reply with '00000000'. Do not include any other words.\n\nTEXT:\n{text_content[:4000]}"
                        llm_resp = ollama.generate(model=LLM_MODEL, prompt=prompt)
                        date_str = llm_resp['response'].strip()
                        extracted = ''.join(filter(str.isdigit, date_str))
                        if len(extracted) >= 8:
                            date_digits = extracted[:8]
                    except Exception as e:
                        raise Exception(f"Failed to read PDF. It might be an HTML error page instead of a real PDF: {e}")
                
                systematic_name = f"{date_digits}_{job['systematic_base_name']}_{slug}{f_ext}"
                
                crawler_db.update_job_status(job_id, "Running", f"[{processed_count}/{len(found_files)}] Checking Chatbot API...")
                
                check_res = requests.get(f"{CHATBOT_API_URL}/documents/check", params={"name": systematic_name})
                if check_res.status_code == 200 and check_res.json().get("exists"):
                    crawler_db.log_document(job_id, f_url, systematic_name, date_digits, "Skipped (Already exists)")
                else:
                    crawler_db.update_job_status(job_id, "Running", f"[{processed_count}/{len(found_files)}] Uploading...")
                    with open(temp_path, 'rb') as f_up:
                        files = {'file': (systematic_name, f_up, 'application/octet-stream')}
                        upload_res = requests.post(f"{CHATBOT_API_URL}/documents/upload", files=files)
                        
                    if upload_res.status_code == 200:
                        crawler_db.log_document(job_id, f_url, systematic_name, date_digits, "Downloaded & Uploaded")
                    else:
                        crawler_db.log_document(job_id, f_url, systematic_name, date_digits, "Upload Failed")
                        
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    
            except Exception as e:
                crawler_db.log_document(job_id, f_url, f"Error_{slug}{f_ext}", "00000000", f"Error: {e}")

        crawler_db.update_job_status(job_id, "Idle", f"Completed. Processed {len(found_files)} files.")

    except Exception as e:
        import traceback
        traceback.print_exc()
        crawler_db.update_job_status(job_id, "Idle", f"Critical Error: {str(e)}")

def crawl_task(job_id):
    thread = threading.Thread(target=crawl_task_sync, args=(job_id,))
    thread.daemon = True
    thread.start()
