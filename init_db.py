"""Initialize the SQLite database and seed it with dummy data."""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customer_tracker.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS Customer (
            Customerid            INTEGER PRIMARY KEY AUTOINCREMENT,
            CustomerName          TEXT    NOT NULL,
            credit_limit          REAL,
            value_segment         TEXT,
            branch                TEXT,
            sector                TEXT,
            region                TEXT,
            portfolio_manager     TEXT,
            foreign_trade_volume  REAL,
            memzuc_151_volume     REAL,
            memzuc_152_volume     REAL,
            LogoFilename          TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS CustomerDeals (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            customerid    INTEGER NOT NULL,
            contact_name  TEXT,
            deal_size     REAL,
            expected_pricing_pa  REAL,
            currency      INTEGER DEFAULT 0,
            status        INTEGER,
            dealtype      INTEGER,
            notes         TEXT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customerid) REFERENCES Customer(Customerid) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS Comment (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id   INTEGER NOT NULL,
            author        TEXT    NOT NULL,
            content       TEXT    NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES Customer(Customerid) ON DELETE CASCADE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS Parameter (
            ParamType        TEXT,
            ParamCode        TEXT,
            ParamDescription TEXT,
            ParamValue       TEXT,
            ParamValue2      TEXT,
            ParamValue3      TEXT,
            ParamValue4      TEXT,
            ParamValue5      TEXT,
            ParamValue6      TEXT,
            ParamValue7      TEXT,
            LanguageId       INTEGER DEFAULT 0,
            PRIMARY KEY (ParamType, ParamCode, LanguageId)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS CustomerAnalysis (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id   INTEGER NOT NULL,
            analysis_text TEXT    NOT NULL,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (customer_id) REFERENCES Customer(Customerid) ON DELETE CASCADE
        )
    """)

    # ── Migrate existing DB: add new columns if missing ─────────────────────
    try:
        cur.execute("ALTER TABLE CustomerDeals ADD COLUMN expected_pricing_pa REAL")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE CustomerDeals ADD COLUMN currency INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        cur.execute("ALTER TABLE Customer ADD COLUMN IsStructured INTEGER DEFAULT 0")
        # Existing customers should remain visible
        cur.execute("UPDATE Customer SET IsStructured=1 WHERE IsStructured IS NULL OR IsStructured=0")
    except Exception:
        pass

    try:
        cur.execute("ALTER TABLE Parameter ADD COLUMN LanguageId INTEGER DEFAULT 0")
        # Migrate PK constraint by table recreation
        cur.execute("""
            CREATE TABLE Parameter_tmp (
                ParamType TEXT, ParamCode TEXT, ParamDescription TEXT, ParamValue TEXT,
                ParamValue2 TEXT, ParamValue3 TEXT, ParamValue4 TEXT, ParamValue5 TEXT,
                ParamValue6 TEXT, ParamValue7 TEXT, LanguageId INTEGER DEFAULT 0,
                PRIMARY KEY (ParamType, ParamCode, LanguageId)
            )
        """)
        cur.execute("INSERT INTO Parameter_tmp SELECT *, 0 FROM Parameter")
        cur.execute("DROP TABLE Parameter")
        cur.execute("ALTER TABLE Parameter_tmp RENAME TO Parameter")
    except Exception:
        pass

    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS Dictionary (
                Id TEXT,
                Description TEXT,
                LanguageId INTEGER,
                PRIMARY KEY (Id, LanguageId)
            )
        """)
    except Exception as e:
        print(f"Dictionary table creation error: {e}")

    # ── Seed Sector parameters (English=0) ──────────────────────────────────────
    sector_params = [
        ("Sector", "1", "Retail", ""),
        ("Sector", "2", "Technology", ""),
        ("Sector", "3", "Infrastructure", ""),
        ("Sector", "4", "Financials", ""),
        ("Sector", "5", "Healthcare", ""),
        ("Sector", "6", "Energy", ""),
        ("Sector", "7", "Telecom", ""),
        ("Sector", "8", "Manufacturing", ""),
        ("Sector", "9", "Real Estate", ""),
        ("Sector", "10", "Automotive", ""),
        ("Sector", "11", "Other", ""),
    ]
    for pt, pc, desc, val in sector_params:
        cur.execute(
            "INSERT OR IGNORE INTO Parameter (ParamType, ParamCode, ParamDescription, ParamValue, LanguageId) VALUES (?, ?, ?, ?, 0)",
            (pt, pc, desc, val)
        )

    # ── Seed FEC (currency) parameters (English=0) ──────────────────────────────────────
    fec_params = [
        ("FEC", "0",  "Turkish Lira",     "TRY"),
        ("FEC", "1",  "American Dollar",  "USD"),
        ("FEC", "19", "EURO",             "EUR"),
    ]
    for pt, pc, desc, val in fec_params:
        cur.execute(
            "INSERT OR IGNORE INTO Parameter (ParamType, ParamCode, ParamDescription, ParamValue, LanguageId) VALUES (?, ?, ?, ?, 0)",
            (pt, pc, desc, val)
        )

    # ── Seed Status logos in ParamValue3 ────────────────────────────────────
    status_logos = {
        "1": "🎯",   # Lead
        "2": "📄",   # Proposal
        "3": "🔍",   # Due Diligence
        "4": "✅",   # Closed Won
        "5": "❌",   # Closed Lost
        "6": "🧪",   # Test
    }
    for code, logo in status_logos.items():
        cur.execute(
            "UPDATE Parameter SET ParamValue3=? WHERE ParamType='Status' AND ParamCode=? AND LanguageId=0",
            (logo, code)
        )

    # ── Seed Turkish Parameters (LanguageId=1) ────────────────────────────────────
    tr_params = [
        ("Status", "1", "Aday", "Lead", 1),
        ("Status", "2", "Teklif", "Proposal", 1),
        ("Status", "3", "İnceleme", "Due Diligence", 1),
        ("Status", "4", "Kazanıldı", "Closed Won", 1),
        ("Status", "5", "Kaybedildi", "Closed Lost", 1),
        ("Status", "6", "Test", "Test", 1),
        ("DealType", "1", "Proje Finansmanı", "Project Finance", 1),
        ("DealType", "2", "Satın Alma Finansmanı", "Acquisition Finance", 1),
        ("DealType", "3", "Sermaye", "Equity", 1),
        ("FEC", "0", "Türk Lirası", "TRY", 1),
        ("FEC", "1", "Amerikan Doları", "USD", 1),
        ("FEC", "19", "Euro", "EUR", 1),
        ("Sector", "1", "Perakende", "", 1),
        ("Sector", "2", "Teknoloji", "", 1),
        ("Sector", "3", "Altyapı", "", 1),
        ("Sector", "4", "Finans", "", 1),
        ("Sector", "5", "Sağlık", "", 1),
        ("Sector", "6", "Enerji", "", 1),
        ("Sector", "7", "Telekomünikasyon", "", 1),
        ("Sector", "8", "Üretim", "", 1),
        ("Sector", "9", "Gayrimenkul", "", 1),
        ("Sector", "10", "Otomotiv", "", 1),
        ("Sector", "11", "Diğer", "", 1),
    ]
    for pt, pc, desc, val, lang in tr_params:
        cur.execute(
            "INSERT OR IGNORE INTO Parameter (ParamType, ParamCode, ParamDescription, ParamValue, LanguageId) VALUES (?, ?, ?, ?, ?)",
            (pt, pc, desc, val, lang)
        )
        if pt == "Status" and pc in status_logos:
            cur.execute(
                "UPDATE Parameter SET ParamValue3=? WHERE ParamType='Status' AND ParamCode=? AND LanguageId=1",
                (status_logos[pc], pc)
            )

    # ── Seed UI Dictionary (0=EN, 1=TR) ──────────────────────────────────────
    dict_seed = [
        ("nav_dashboard", "Dashboard", "Özet Ekranı"),
        ("nav_deals", "Deals", "Fırsatlar"),
        ("nav_overview", "Overview", "Genel Bakış"),
        ("nav_management", "Management", "Yönetim"),
        
        ("ov_refresh_all", "Refresh All AI Analysis", "Tüm Yapay Zeka Analizlerini Yenile"),
        ("ov_refreshing", "Refreshing AI Analysis...", "YZ Analizleri Yenileniyor..."),
        ("ov_refresh_complete", "Refresh complete!", "Yenileme tamamlandı!"),
        ("ov_subtitle", "Select a customer to view their profile, active deals, and team memos", "Profilini, aktif fırsatlarını ve takım notlarını görüntülemek için bir müşteri seçin."),

        
        ("dash_title", "Portfolio Dashboard", "Portföy Özeti"),
        ("dash_subtitle", "High-level overview of active tracking limits and current pipeline.", "Aktif limitler ve mevcut fırsatların genel özeti."),
        ("dash_limits_title", "Total Limits & Volumes", "Toplam Limitler & Hacimler"),
        ("dash_credit_limit", "Global Credit Limit", "Global Kredi Limiti"),
        ("dash_foreign_trade", "Foreign Trade Volume", "Dış Ticaret Hacmi"),
        ("dash_pipeline_title", "Pipeline by Status", "Duruma Göre Fırsatlar"),
        ("dash_segment_title", "Customer Segments", "Müşteri Segmentleri"),
        ("dash_region_title", "Regional Distribution", "Bölgesel Dağılım"),
        
        ("mgmt_title", "Customer Management", "Müşteri Yönetimi"),
        ("mgmt_subtitle", "Add customers from the company database to your structured finance tracking", "Kurum veritabanındaki müşterileri yapılandırılmış finansman takibine ekleyin"),
        ("mgmt_add_title", "Add Customer", "Müşteri Ekle"),
        ("mgmt_acc_label", "Account Number *", "Hesap Numarası *"),
        ("mgmt_acc_ph", "Enter account number", "Hesap numarasını girin"),
        ("mgmt_err_notfound", "Customer could not be found.", "Müşteri bulunamadı."),
        ("mgmt_err_tracked", "Customer is already tracked in structured finance.", "Müşteri zaten yapılandırılmış finansman takibinde."),
        ("mgmt_success", "Customer found ✓", "Müşteri bulundu ✓"),
        ("mgmt_company_col", "Company Name", "Firma Adı"),
        ("mgmt_sector_col", "Sector", "Sektör"),
        ("mgmt_pm_col", "Portfolio Manager", "Portföy Yöneticisi"),
        ("mgmt_btn_add", "+ Add Customer", "+ Müşteri Ekle"),
        ("mgmt_tbl_title", "Tracked Customers", "Takip Edilen Müşteriler"),
        ("mgmt_tbl_acc", "Account #", "Hesap No"),
        ("mgmt_tbl_actions", "Actions", "İşlemler"),
        ("mgmt_btn_edit", "Edit Customer", "Müşteriyi Düzenle"),
        ("mgmt_btn_remove", "Remove", "Kaldır"),
        ("mgmt_empty", "No customers tracked yet. Look up an account number above to add one.", "Henüz takip edilen müşteri yok. Eklemek için yukarıdan hesap numarası arayın."),
        ("mgmt_confirm_remove", "Remove {} from structured finance tracking?", "{} müşterisini takipten çıkarmak istediğinize emin misiniz?"),
        
        ("list_title", "Pipeline Deals", "Fırsat Listesi"),
        ("list_subtitle", "Manage and track all ongoing structured finance opportunities", "Devam eden tüm yapılandırılmış finansman fırsatlarını yönetin ve takip edin"),
        ("list_btn_export", "Export pipeline to Excel", "Fırsatları Excel'e aktar"),
        ("list_btn_export_txt", "Export to Excel", "Excel'e Aktar"),
        ("list_add_title", "Add New Deal", "Yeni Fırsat Ekle"),
        ("list_sel_customer", "Select Customer", "Müşteri Seçin"),
        ("list_contact", "Contact Name", "İletişim Kişisi"),
        ("list_deal_type", "Deal Type", "Fırsat Tipi"),
        ("list_deal_size", "Deal Size", "Fırsat Büyüklüğü"),
        ("list_exp_pricing", "Expected Pricing p.a.", "Beklenen Yıllık Getiri"),
        ("list_currency", "Currency", "Para Birimi"),
        ("list_status", "Status", "Durum"),
        ("list_notes", "Notes (optional)", "Notlar (isteğe bağlı)"),
        ("list_btn_add_deal", "+ Add Deal", "+ Fırsat Ekle"),
        ("list_tbl_company", "Company", "Firma"),
        ("list_tbl_contact", "Contact", "Kişi"),
        ("list_tbl_details", "Deal Details", "Detaylar"),
        ("list_tbl_size", "Size & Pricing", "Büyüklük & Getiri"),
        ("list_tbl_status", "Status", "Durum"),
        ("list_empty", "No deals available.", "Henüz fırsat bulunmuyor."),
        
        ("dd_title", "Deal Overview", "Fırsat Özeti"),
        ("dd_btn_back", "← Back to Pipeline", "← Listeye Dön"),
        ("dd_btn_edit", "Edit Deal", "Fırsatı Düzenle"),
        ("dd_id", "Deal ID", "Fırsat ID"),
        ("dd_company", "Company", "Firma"),
        ("dd_type", "Type", "Fırsat Tipi"),
        ("dd_size", "Size", "Büyüklük"),
        ("dd_pricing", "Expected Pricing", "Beklenen Getiri"),
        ("dd_currency", "Currency", "Para Birimi"),
        ("dd_created", "Created At", "Oluşturulma Tarihi"),
        ("dd_notes", "Notes", "Notlar"),
        ("dd_no_notes", "No notes provided.", "Not eklenmemiş."),
        ("dd_btn_delete", "Delete Deal", "Fırsatı Sil"),
        ("dd_confirm_delete", "Are you sure you want to delete this deal?", "Bu fırsatı silmek istediğinize emin misiniz?"),
        
        ("ed_title", "Edit Deal", "Fırsatı Düzenle"),
        ("ed_btn_cancel", "Cancel", "İptal"),
        ("ed_btn_save", "Save Changes", "Değişiklikleri Kaydet"),
        
        ("ov_title", "Customer Overview", "Müşteri Özeti"),
        ("ov_btn_back", "← Back to Customers", "← Müşterilere Dön"),
        ("ov_ai_title", "AI Profile Analysis", "Yapay Zeka Müşteri Analizi"),
        ("ov_ai_btn", "Generate New Analysis", "Yeni Analiz Oluştur"),
        ("ov_ai_empty", "No analysis available. Click the button above to generate one.", "Henüz analiz bulunmuyor. Üretmek için yukarıdaki butona tıklayın."),
        ("ov_deals_title", "Active Deals", "Aktif Fırsatlar"),
        ("ov_comments_title", "Comments & Updates", "Yorumlar ve Güncellemeler"),
        ("ov_comment_author", "Your Name", "İsminiz"),
        ("ov_comment_content", "Add a comment or update...", "Bir yorum veya güncelleme ekleyin..."),
        ("ov_comment_btn", "Post Update", "Güncelle"),
        ("ov_comment_empty", "No comments yet.", "Henüz yorum yok."),
        
        ("ce_title", "Edit Customer Profile", "Müşteri Profilini Düzenle"),
        ("ce_fin_info", "Financial Information (Internal)", "Finansal Bilgiler (İç Sistem)"),
        ("ce_fin_desc", "These fields reflect core banking data and are read-only.", "Bu alanlar temel bankacılık verilerini gösterir ve salt okunurdur."),
        ("ce_btn_save", "Save Updates", "Güncellemeleri Kaydet")
    ]
    for key, en_val, tr_val in dict_seed:
        cur.execute("INSERT OR REPLACE INTO Dictionary (Id, Description, LanguageId) VALUES (?, ?, 0)", (key, en_val))
        cur.execute("INSERT OR REPLACE INTO Dictionary (Id, Description, LanguageId) VALUES (?, ?, 1)", (key, tr_val))

    conn.commit()
    conn.close()
    print(f"Database schema synced at {DB_PATH}")

if __name__ == "__main__":
    init_db()
