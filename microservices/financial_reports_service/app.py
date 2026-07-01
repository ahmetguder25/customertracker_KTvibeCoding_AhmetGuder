import os
import sys
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS

# Add project root to sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from app.shared.db import get_db
from app.shared.config import CUSTOMER_DOCS_FOLDER
from microservices.financial_reports_service.extractor import extract_financial_report_from_pdf

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

@app.route("/api/health", methods=["GET"])
def api_health():
    return jsonify({"status": "ok", "service": "financial_reports", "port": 5005})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    return jsonify({"success": True, "message": "Service reset complete."})

@app.route("/api/extract", methods=["POST"])
def api_extract():
    data = request.get_json() or {}
    doc_id = data.get("doc_id") or data.get("document_id")
    
    if not doc_id:
        return jsonify({"error": "Missing doc_id parameter"}), 400
        
    conn = get_db()
    try:
        row = conn.execute("SELECT DocID, CustomerID, FileName, DocName FROM BOA.COR.CustomerDocument WHERE DocID=?", (doc_id,)).fetchone()
        if not row:
            return jsonify({"error": f"Document {doc_id} not found in database"}), 404
            
        filename = row["FileName"]
        customer_id = row["CustomerID"]
        filepath = os.path.join(CUSTOMER_DOCS_FOLDER, filename)
        
        if not os.path.exists(filepath):
            return jsonify({"error": f"File {filename} not found on disk"}), 404
            
        # Extract rows
        db_rows, periods = extract_financial_report_from_pdf(filepath, doc_id, customer_id)
        
        if not db_rows:
            return jsonify({"error": "No financial statements could be extracted from this PDF"}), 422
            
        # Delete existing report lines for this document
        conn.execute("DELETE FROM BOA.STF.FinancialReports WHERE DocID=?", (doc_id,))
        
        # Insert new rows
        insert_sql = """
            INSERT INTO BOA.STF.FinancialReports (
                DocID, CustomerID, StatementType, PeriodCode, PeriodDate, PeriodLabel,
                Section, ParentLabel, LineLabel, NoteRef, Amount, ScaleMultiplier,
                Depth, IsSubTotal, LineOrder
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        for r in db_rows:
            conn.execute(insert_sql, (
                r["DocID"], r["CustomerID"], r["StatementType"], r["PeriodCode"], r["PeriodDate"], r["PeriodLabel"],
                r["Section"], r["ParentLabel"], r["LineLabel"], r["NoteRef"], r["Amount"], r["ScaleMultiplier"],
                r["Depth"], r["IsSubTotal"], r["LineOrder"]
            ))
            
        conn.commit()
        return jsonify({
            "success": True,
            "message": f"Successfully extracted {len(db_rows)} financial line items across {len(periods)} periods.",
            "doc_id": doc_id,
            "periods": periods,
            "rows_count": len(db_rows)
        }), 200
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        if conn:
            conn.rollback()
        return jsonify({"error": f"Extraction failed: {str(e)}"}), 500
    finally:
        if conn:
            conn.close()

@app.route("/api/report", methods=["GET"])
def api_report():
    doc_id = request.args.get("doc_id")
    period_code = request.args.get("period_code")
    
    if not doc_id:
        return jsonify({"error": "Missing doc_id parameter"}), 400
        
    conn = get_db()
    try:
        sql = "SELECT * FROM BOA.STF.FinancialReports WHERE DocID=? AND IsActive=1"
        params = [doc_id]
        if period_code:
            sql += " AND PeriodCode=?"
            params.append(period_code)
        sql += " ORDER BY PeriodCode DESC, LineOrder ASC"
        
        rows = conn.execute(sql, params).fetchall()
        
        # Build period summary and organized rows
        periods_set = {}
        for r in rows:
            p_code = r["PeriodCode"]
            if p_code not in periods_set:
                periods_set[p_code] = {
                    "code": p_code,
                    "date": str(r["PeriodDate"]) if r["PeriodDate"] else None,
                    "label": r["PeriodLabel"]
                }
                
        # Return structured list
        data = [dict(r) for r in rows]
        # format date objects for json serialization
        for d in data:
            if d.get("PeriodDate"):
                d["PeriodDate"] = str(d["PeriodDate"])
            if d.get("ExtractedAt"):
                d["ExtractedAt"] = str(d["ExtractedAt"])
                
        return jsonify({
            "success": True,
            "doc_id": doc_id,
            "periods": list(periods_set.values()),
            "data": data
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    app.run(port=5005, debug=True)
