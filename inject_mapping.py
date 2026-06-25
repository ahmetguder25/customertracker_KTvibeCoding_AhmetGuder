import os
import json
import sqlite3
import sys

# Connect to the local Sparx AI database on the Mac
DB_PATH = os.path.join(os.path.dirname(__file__), 'microservices', 'sparx_ai_service', 'rag_state.db')

def inject_mapping(document_id, json_path):
    if not os.path.exists(json_path):
        print(f"Error: Could not find {json_path}")
        return

    with open(json_path, 'r', encoding='utf-8') as f:
        summaries = json.load(f)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. Clear any existing summaries for this document
    c.execute('DELETE FROM graph_summaries WHERE document_id = ?', (document_id,))
    
    # 2. Insert the new summaries from Linux
    for item in summaries:
        c.execute('''
            INSERT INTO graph_summaries (document_id, community_id, summary_text, embedding)
            VALUES (?, ?, ?, ?)
        ''', (document_id, item['community_id'], item['summary_text'], json.dumps(item['embedding'])))
        
    # 3. Mark the Mapping task as 100% Completed so the UI unlocks the Analysis chat
    c.execute('''
        INSERT INTO document_tasks (document_id, task_type, status, progress_message, percent_complete, updated_at)
        VALUES (?, 'Mapping', 'Completed', 'Manually injected from Linux vLLM cluster.', 100, datetime('now'))
        ON CONFLICT(document_id, task_type) DO UPDATE SET 
            status=excluded.status, 
            progress_message=excluded.progress_message, 
            percent_complete=excluded.percent_complete,
            updated_at=excluded.updated_at
    ''')

    conn.commit()
    conn.close()
    
    print(f"Success! Injected {len(summaries)} clustered summaries into the Mac database.")
    print("You can now go to the Customer Tracker UI, open this document in Sparx AI, and start chatting!")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python inject_mapping.py <document_id> <path_to_json>")
    else:
        inject_mapping(sys.argv[1], sys.argv[2])
