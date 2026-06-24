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

huey = SqliteHuey(filename=os.path.join(BASE_DIR, 'crawler_queue.db'))

CHATBOT_API_URL = "http://127.0.0.1:5001/api"
LLM_MODEL = "qwen2.5:7b"

@huey.task()
def crawl_task(job_id):
    conn = crawler_db.get_db()
    job = conn.execute("SELECT * FROM crawler_jobs WHERE id=?", (job_id,)).fetchone()
    conn.close()
    if not job: return

    try:
        crawler_db.update_job_status(job_id, "Running", "Fetching URL...")
        
        # 1. Fetch Target URL
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(job["target_url"], headers=headers, timeout=15)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 2. Find PDF link matching query
        query = job["search_query"].lower()
        pdf_url = None
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text(strip=True).lower()
            if '.pdf' in href.lower() and (query in href.lower() or query in text):
                pdf_url = urljoin(job["target_url"], href)
                break
                
        if not pdf_url:
            crawler_db.update_job_status(job_id, "Idle", "No matching PDF found on page.")
            return

        crawler_db.update_job_status(job_id, "Running", f"Downloading PDF...")
        
        # 3. Download PDF
        pdf_response = requests.get(pdf_url, headers=headers, timeout=30)
        pdf_response.raise_for_status()
        temp_pdf_path = os.path.join(TEMP_DIR, f"temp_{job_id}.pdf")
        with open(temp_pdf_path, 'wb') as f:
            f.write(pdf_response.content)

        crawler_db.update_job_status(job_id, "Running", "Analyzing dates with AI...")
        
        # 4. Extract Text from last pages
        doc = fitz.open(temp_pdf_path)
        num_pages = len(doc)
        start_page = max(0, num_pages - 5)
        text_content = ""
        for i in range(start_page, num_pages):
            text_content += doc.load_page(i).get_text()
        doc.close()

        # 5. Ask LLM for the date
        prompt = f"""Extract the most recent update date or publish date from the following text (which is from the end of a regulatory document).
Your response MUST be ONLY the date formatted as YYYYMMDD. For example: 20251203
If you absolutely cannot find any date, reply with '00000000'. Do not include any other words.

TEXT:
{text_content[:4000]}
"""
        llm_resp = ollama.generate(model=LLM_MODEL, prompt=prompt)
        date_str = llm_resp['response'].strip()
        
        # Sanitize date (extract only digits)
        date_digits = ''.join(filter(str.isdigit, date_str))
        if len(date_digits) >= 8:
            date_digits = date_digits[:8]
        else:
            date_digits = "00000000"
            
        systematic_name = f"{date_digits}_{job['systematic_base_name']}.pdf"

        crawler_db.update_job_status(job_id, "Running", "Checking Chatbot API...")

        # 6. Check if exists in Chatbot API
        check_res = requests.get(f"{CHATBOT_API_URL}/documents/check", params={"name": systematic_name})
        if check_res.status_code == 200 and check_res.json().get("exists"):
            crawler_db.log_document(job_id, pdf_url, systematic_name, date_digits, "Skipped (Already up to date)")
            crawler_db.update_job_status(job_id, "Idle", f"Skipped: {systematic_name} already exists.")
        else:
            crawler_db.update_job_status(job_id, "Running", "Uploading to Chatbot...")
            # 7. Upload to Chatbot API
            with open(temp_pdf_path, 'rb') as f:
                files = {'file': (systematic_name, f, 'application/pdf')}
                upload_res = requests.post(f"{CHATBOT_API_URL}/documents/upload", files=files)
            
            if upload_res.status_code == 200:
                crawler_db.log_document(job_id, pdf_url, systematic_name, date_digits, "Downloaded & Uploaded")
                crawler_db.update_job_status(job_id, "Idle", f"Success: Added {systematic_name}")
            else:
                crawler_db.log_document(job_id, pdf_url, systematic_name, date_digits, "Upload Failed")
                crawler_db.update_job_status(job_id, "Idle", f"Failed to upload to Chatbot API: {upload_res.text}")

        # Cleanup
        if os.path.exists(temp_pdf_path):
            os.remove(temp_pdf_path)

    except Exception as e:
        crawler_db.update_job_status(job_id, "Idle", f"Error: {str(e)}")
