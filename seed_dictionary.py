"""
Seed / fill missing Dictionary entries for both English (0) and Turkish (1).
Run with:   python3 seed_dictionary.py

Uses T-SQL MERGE so existing entries are preserved (only INSERTs missing rows).
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.environ.setdefault("FLASK_APP", "app")

from app import app, get_db

# ── All dictionary keys with EN / TR values ──────────────────────────────────
ENTRIES = [
    # ─── Navigation / Shell ───
    ("nav_backlog",         "Backlog",                                "İş Listesi"),
    ("nav_deals",           "Deals",                                  "İşler"),
    ("nav_management",      "Mgmt",                                   "Yönetim"),
    ("nav_overview",        "Overview",                                "Genel Bakış"),
    ("nav_signout",         "Sign Out",                                "Çıkış Yap"),
    ("nav_footer",          "&copy; 2026 Structured Finance &mdash; Customer Tracker",
                            "&copy; 2026 Yapılandırılmış Finans &mdash; Müşteri Takibi"),
    ("nav_products",        "Products",                                "Ürünler"),
    ("nav_okrs",            "OKRs",                                    "OKR'ler"),
    ("nav_projects",        "Projects",                                "Projeler"),
    ("nav_dashboard",       "Dashboard",                               "Portföy Özeti"),
    ("nav_new_task",        "New Task",                                "Yeni Görev"),

    # ─── Login ───
    ("login_title",         "Customer Tracker — Login",                "Müşteri Takibi — Giriş"),
    ("login_no_users",      "No users found in database.",             "Veritabanında kullanıcı bulunamadı."),

    # ─── Env Login ───
    ("env_title",           "Customer Tracker — Connect",              "Müşteri Takibi — Bağlan"),
    ("env_subtitle",        "Select Target Environment",               "Hedef Ortamı Seçin"),
    ("env_local_server",    "LOCALHOST:1433",                           "LOCALHOST:1433"),
    ("env_local_title",     "Local",                                   "Yerel"),
    ("env_local_desc",      "Docker / Express — safe for dev/test.",   "Docker / Express — geliştirme/test için güvenli."),
    ("env_local_badge",     "DEV",                                     "GELİŞTİRME"),
    ("env_prod_server",     "SRVDNZ",                                  "SRVDNZ"),
    ("env_prod_title",      "Prod",                                    "Üretim"),
    ("env_prod_desc",       "Production SQL Server — live data, permanent changes.",
                            "Üretim SQL Server — canlı veri, kalıcı değişiklikler."),
    ("env_prod_badge",      "WIN AUTH",                                "WIN AUTH"),
    ("env_warning",         "PRODUCTION DATA — changes are permanent.", "ÜRETİM VERİSİ — değişiklikler kalıcıdır."),
    ("env_connect_test",    "Connect to Local",                        "Yerel'e Bağlan"),
    ("env_connect_prod",    "Connect to Prod",                         "Üretime Bağlan"),
    ("env_connect_local",   "Connect to Local",                        "Yerel'e Bağlan"),

    # ─── Dashboard ───
    ("dash_title",          "Portfolio Dashboard",                     "Portföy Özeti"),
    ("dash_subtitle",       "High-level overview of active tracking limits and current pipeline.",
                            "Aktif limitler ve mevcut fırsatların genel özeti."),
    ("dash_total_deals",    "Total Deals",                             "İşlerin Toplamı"),
    ("dash_active_pipeline","Active Pipeline",                         "Aktif İşler"),
    ("dash_win_rate",       "Win Rate",                                "Kazanma Oranı"),
    ("dash_credit_limit",   "Global Credit Limit",                     "Global Kredi Limiti"),
    ("dash_foreign_trade",  "Foreign Trade Volume",                    "Dış Ticaret Hacmi"),
    ("dash_151_vol",        "Memzuc 151 Vol",                          "Memzuc 151 Hacim"),
    ("dash_152_vol",        "Memzuc 152 Vol",                          "Memzuc 152 Hacim"),
    ("dash_pipeline_title", "Pipeline by Status",                      "Duruma Göre Fırsatlar"),
    ("dash_segment_title",  "Customer Segments",                       "Müşteri Segmentleri"),
    ("dash_region_title",   "Regional Distribution",                   "Bölge Dağılımı"),
    ("dash_empty_recent",   "No customers found.",                     "Müşteri bulunamadı."),
    ("dash_chatbot_title",  "AAOIFI Standards — AI Assistant",         "AAOIFI Standartları — Yapay Zeka Asistanı"),
    ("dash_chatbot_ready",  "Ready. Ask me anything about AAOIFI Sharia Standards — I will answer strictly in English using the document context.",
                            "Hazır. AAOIFI Şeriat Standartları hakkında dilediğinizi sorun — belge bağlamını kullanarak cevap vereceğim."),
    ("dash_chatbot_placeholder", "Type your question about AAOIFI standards...",
                            "AAOIFI standartları hakkında sorunuzu yazın..."),
    ("dash_chatbot_send",   "Send",                                    "Gönder"),

    # ─── Backlog ───
    ("bl_title",            "Global Backlog",                          "Genel İş Listesi"),
    ("bl_subtitle",         "All open work items across deals and projects",
                            "Tüm açık görevler — fırsatlar ve projeler"),
    ("bl_all_types",        "All Types",                               "Tüm Tipler"),
    ("bl_projects",         "Projects",                                "Projeler"),
    ("bl_deals",            "Deals",                                   "İşler"),
    ("bl_all_status",       "All Status",                              "Tüm Durumlar"),
    ("bl_not_started",      "Not Started",                             "Başlamadı"),
    ("bl_in_progress",      "In Progress",                             "Devam Ediyor"),
    ("bl_blocked",          "Blocked",                                 "Engellendi"),
    ("bl_all_assignees",    "All Assignees",                           "Tüm Sorumlular"),
    ("bl_any_deadline",     "Any Deadline",                            "Tüm Tarihler"),
    ("bl_overdue",          "Overdue",                                 "Gecikmiş"),
    ("bl_due_today",        "Due Today",                               "Bugün Bitiyor"),
    ("bl_this_week",        "This Week",                               "Bu Hafta"),
    ("bl_no_deadline",      "No Deadline",                             "Tarihsiz"),
    ("bl_col_title",        "Title / Descriptor",                      "Başlık / Açıklama"),
    ("bl_col_deal_flow",    "Deal / Flow",                             "İş / Akış"),
    ("bl_col_type",         "Type",                                    "Tip"),
    ("bl_col_status",       "Status",                                  "Durum"),
    ("bl_col_deadline",     "Deadline",                                "Bitiş Tarihi"),
    ("bl_empty",            "All clear — no open work items.",         "Temiz — açık görev yok."),

    # ─── Deals List ───
    ("list_title",          "Pipeline Deals",                          "Fırsat Listesi"),
    ("list_subtitle",       "All tracked deals across active customers",
                            "Aktif müşterilerdeki tüm takip edilen fırsatlar"),
    ("list_btn_add_deal",   "New Deal",                                "Yeni İş"),
    ("list_btn_export",     "Export",                                  "Dışa Aktar"),
    ("list_btn_export_txt", "Export",                                  "Dışa Aktar"),
    ("list_add_title",      "Add New Deal",                            "Yeni İş Ekle"),
    ("list_sel_customer",   "Customer",                                "Müşteri"),
    ("list_contact",        "Contact",                                 "İletişim"),
    ("list_deal_size",      "Deal Size",                               "İş Büyüklüğü"),
    ("list_exp_pricing",    "Pricing P.A.",                            "Fiyat Beklentisi"),
    ("list_currency",       "Currency",                                "Döviz Cinsi"),
    ("list_status",         "Status",                                  "Durum"),
    ("list_deal_type",      "Deal Type",                               "İş Tipi"),
    ("list_notes",          "Notes",                                   "Notlar"),
    ("list_tbl_company",    "Company",                                 "Firma"),
    ("list_tbl_contact",    "Contact",                                 "İletişim"),
    ("list_tbl_seg",        "Seg",                                     "Seg"),
    ("list_tbl_branch",     "Branch",                                  "Şube"),
    ("list_tbl_actions",    "Actions",                                 "İşlemler"),
    ("list_empty",          "No deals found. Click \"New Deal\" to create one.",
                            "İş bulunamadı. Yeni iş oluşturmak için \"Yeni İş\" butonuna tıklayın."),
    ("list_btn_cancel",     "Cancel",                                  "İptal"),
    ("list_btn_cust",       "Cust",                                    "Müş"),
    ("list_btn_edit",       "Edit",                                    "Düzenle"),
    ("list_btn_del",        "Del",                                     "Sil"),
    ("list_confirm_delete", "Delete this deal?",                       "Bu işi silmek istediğinize emin misiniz?"),

    # ─── Deal Detail ───
    ("detail_btn_back",     "Back to Deals",                           "İşlere Dön"),
    ("detail_size",         "Deal Size",                               "İş Büyüklüğü"),
    ("detail_pricing",      "Pricing P.A.",                            "Fiyat Beklentisi"),
    ("detail_currency",     "Currency",                                "Döviz Cinsi"),
    ("detail_notes",        "Deal Notes",                              "İş Notları"),
    ("detail_no_notes",     "No notes.",                               "Not eklenmemiş."),
    ("detail_btn_edit",     "Edit",                                    "Düzenle"),
    ("detail_timeline",     "Status Timeline",                         "Durum Geçmişi"),

    # ─── Customer Edit ───
    ("edit_back",           "Back to Management",                      "Yönetime Dön"),
    ("edit_title",          "Edit: {}",                                "Düzenle: {}"),
    ("edit_section_core",   "Core Customer Information",               "Temel Müşteri Bilgileri"),
    ("edit_logo_label",     "Upload Logo",                             "Logo Yükle"),
    ("edit_btn_save",       "Save",                                    "Kaydet"),
    ("edit_section_fin",    "Financial Data",                          "Finansal Veriler"),

    # ─── Management ───
    ("mgmt_title",          "Customer Management",                     "Müşteri Yönetimi"),
    ("mgmt_subtitle",       "Add customers from the company database to your structured finance tracking",
                            "Şirket veritabanından yapılandırılmış finans takibinize müşteri ekleyin"),
    ("mgmt_tab_customers",  "Customers",                               "Müşteriler"),
    ("mgmt_tab_stakeholders","Stakeholders",                           "Paydaşlar"),
    ("mgmt_add_title",      "Add Customer",                            "Müşteri Ekle"),
    ("mgmt_acc_label",      "Account # *",                             "Hesap No *"),
    ("mgmt_acc_ph",         "Enter account number",                    "Hesap numarasını girin"),
    ("mgmt_err_notfound",   "Customer not found.",                     "Müşteri bulunamadı."),
    ("mgmt_err_tracked",    "Already tracked.",                        "Zaten takip ediliyor."),
    ("mgmt_success",        "Customer found ✓",                        "Müşteri bulundu ✓"),
    ("mgmt_company_col",    "Company",                                 "Firma"),
    ("mgmt_branch_col",     "Branch",                                  "Şube"),
    ("mgmt_region_col",     "Region",                                  "Bölge"),
    ("mgmt_segment_col",    "Segment",                                 "Segment"),
    ("mgmt_pm_col",         "Portfolio Manager",                       "Portföy Yöneticisi"),
    ("mgmt_class_col",      "Class",                                   "Sınıf"),
    ("mgmt_sector_col",     "Sector",                                  "Sektör"),
    ("mgmt_btn_add",        "+ Add Customer",                          "+ Müşteri Ekle"),
    ("mgmt_btn_fetch",      "Fetch",                                   "Getir"),
    ("mgmt_tbl_title",      "Tracked Customers",                      "Takip Edilen Müşteriler"),
    ("mgmt_btn_sync",       "Sync All",                                "Tümünü Güncelle"),
    ("mgmt_tbl_acc",        "Account #",                               "Hesap No"),
    ("mgmt_tbl_actions",    "Actions",                                 "İşlemler"),
    ("mgmt_btn_edit",       "Edit",                                    "Düzenle"),
    ("mgmt_btn_remove",     "Del",                                     "Sil"),
    ("mgmt_confirm_remove", "Remove {}?",                              "{} silinsin mi?"),
    ("mgmt_empty",          "No customers tracked.",                   "Takip edilen müşteri yok."),
    ("mgmt_prod_only",      "Prod Only",                               "Sadece Üretim"),
    ("mgmt_err_empty",      "Enter account number.",                   "Hesap numarasını girin."),
    ("mgmt_err_conn",       "Cannot connect to SRVDNZ.",              "SRVDNZ'ye bağlanılamıyor."),
    ("mgmt_err_query",      "Query error.",                            "Sorgu hatası."),
    ("mgmt_sync_title",     "Synchronizing...",                        "Güncelleniyor..."),
    ("mgmt_sync_btn_cancel","Cancel",                                  "İptal"),
    ("mgmt_sync_btn_finish","Finish & Reload",                         "Bitir ve Yenile"),
    ("mgmt_btn_sync_single","Sync",                                    "Güncelle"),
    ("mgmt_sh_add_title",   "Add Stakeholder",                        "Paydaş Ekle"),
    ("mgmt_sh_name",        "Name",                                    "İsim"),
    ("mgmt_sh_org",         "Org",                                     "Kurum"),
    ("mgmt_sh_dept",        "Dept",                                    "Departman"),
    ("mgmt_sh_email",       "Email",                                   "E-posta"),
    ("mgmt_sh_btn_add",     "+ Add Stakeholder",                      "+ Paydaş Ekle"),
    ("mgmt_sh_title",       "Tracked Stakeholders",                   "Takip Edilen Paydaşlar"),
    ("mgmt_sh_empty",       "No stakeholders.",                        "Paydaş yok."),

    # ─── Products ───
    ("prod_title",          "Products",                                "Ürünler"),
    ("prod_subtitle",       "Financing products available to structure deals",
                            "İş yapılandırmak için mevcut finansman ürünleri"),
    ("prod_btn_add",        "+ Add Product",                           "+ Ürün Ekle"),
    ("prod_col_product",    "Product",                                 "Ürün"),
    ("prod_col_code",       "Code",                                    "Kod"),
    ("prod_col_type",       "Type",                                    "Tip"),
    ("prod_col_contract",   "Contract",                                "Sözleşme"),
    ("prod_col_partner",    "Partner",                                 "Partner"),
    ("prod_col_deals",      "Deals",                                   "İşler"),
    ("prod_empty",          "No products yet.",                        "Henüz ürün yok."),
    ("prod_modal_title",    "New Product",                             "Yeni Ürün"),
    ("prod_name_label",     "Product Name *",                          "Ürün Adı *"),
    ("prod_code_label",     "Code *",                                  "Kod *"),
    ("prod_type_label",     "Type",                                    "Tip"),
    ("prod_islamic_label",  "Islamic Contract",                        "İslami Sözleşme"),
    ("prod_partner_label",  "Partner",                                 "Partner"),
    ("prod_desc_label",     "Description",                             "Açıklama"),
    ("prod_btn_cancel",     "Cancel",                                  "İptal"),
    ("prod_btn_create",     "Create",                                  "Oluştur"),

    # ─── OKRs ───
    ("okr_title",           "OKRs",                                    "OKR'ler"),
    ("okr_subtitle",        "Objectives and Key Results — Strategic Goals",
                            "Hedefler ve Anahtar Sonuçlar — Stratejik Amaçlar"),
    ("okr_btn_add_obj",     "+ Add Objective",                        "+ Hedef Ekle"),
    ("okr_btn_add_kr",      "+ KR",                                    "+ AS"),
    ("okr_btn_del",         "Del",                                     "Sil"),
    ("okr_achieved",        "Achieved",                                "Kazanıldı"),
    ("okr_remove",          "Remove",                                  "Kaldır"),
    ("okr_pipeline",        "pipeline",                                "beklenen"),
    ("okr_no_krs",          "No key results yet.",                    "Henüz anahtar sonuç yok."),
    ("okr_no_objs",         "No objectives yet.",                     "Henüz hedef yok."),
    ("okr_modal_obj",       "New Objective",                           "Yeni Hedef"),
    ("okr_obj_title",       "Title *",                                 "Başlık *"),
    ("okr_obj_period",      "Period",                                  "Dönem"),
    ("okr_obj_desc",        "Description",                             "Açıklama"),
    ("okr_btn_cancel",      "Cancel",                                  "İptal"),
    ("okr_btn_create",      "Create",                                  "Oluştur"),
    ("okr_modal_kr",        "Add Key Result",                          "Anahtar Sonuç Ekle"),
    ("okr_kr_title",        "Title *",                                 "Başlık *"),
    ("okr_kr_target",       "Target *",                                "Hedef *"),
    ("okr_kr_unit",         "Unit",                                    "Birim"),
    ("okr_kr_method",       "Method",                                  "Yöntem"),
    ("okr_btn_add_kr_submit","Add KR",                                 "AS Ekle"),
    ("okr_modal_kr_info",   "Key Result",                              "Anahtar Sonuç"),
    ("okr_contributing",    "Contributing Deals:",                     "Katkıda Bulunan İşler:"),

    # ─── Projects ───
    ("proj_title",          "Projects",                                "Projeler"),
    ("proj_subtitle",       "Internal initiatives and product development",
                            "Dahili girişimler ve ürün geliştirme"),
    ("proj_btn_add",        "+ New Project",                           "+ Yeni Proje"),
    ("proj_no_projects",    "No projects yet.",                        "Henüz proje yok."),
    ("proj_modal_title",    "New Project",                             "Yeni Proje"),
    ("proj_name_label",     "Name *",                                  "Ad *"),
    ("proj_desc_label",     "Description",                             "Açıklama"),
    ("proj_status_label",   "Status",                                  "Durum"),
    ("proj_deadline_label", "Deadline",                                "Bitiş Tarihi"),
    ("proj_link_obj",       "Link to Objective",                       "Hedefe Bağla"),
    ("proj_btn_cancel",     "Cancel",                                  "İptal"),
    ("proj_btn_create",     "Create",                                  "Oluştur"),
    ("proj_due",            "Due",                                     "Bitiş"),

    # ─── Overview ───
    ("ov_title",            "Customer Overview",                       "Müşteri Genel Bakışı"),
    ("ov_subtitle",         "Select a customer to view profile, deals, and memos",
                            "Profil, işler ve notları görmek için bir müşteri seçin"),

    # ─── Common / Shared ───
    ("common_cancel",       "Cancel",                                  "İptal"),
    ("common_save",         "Save",                                    "Kaydet"),
    ("common_delete",       "Delete",                                  "Sil"),
    ("common_edit",         "Edit",                                    "Düzenle"),
    ("common_create",       "Create",                                  "Oluştur"),
    ("common_loading",      "Loading...",                               "Yükleniyor..."),
    ("common_close",        "Close",                                   "Kapat"),
    ("common_select",       "Select…",                                 "Seçiniz…"),
    ("common_none",         "None",                                    "Yok"),

    # ─── Tab Context Menu ───
    ("tab_close",           "Close Tab",                               "Sekmeyi Kapat"),
    ("tab_close_others",    "Close Other Tabs",                        "Diğer Sekmeleri Kapat"),
    ("tab_close_all",       "Close All Tabs",                          "Tüm Sekmeleri Kapat"),

    # ─── Status Footer ───
    ("footer_system",       "System Nominal",                          "Sistem Normal"),

    # ─── User Menu ───
    ("menu_lang",           "Lang",                                    "Dil"),
    ("menu_theme",          "Theme",                                   "Tema"),
    ("menu_light",          "Light",                                   "Açık"),
    ("menu_dark",           "Dark",                                    "Koyu"),

    # ─── Deal Edit ───
    ("de_title",            "Edit Deal",                               "İşi Düzenle"),
    ("de_btn_back",         "← Back to Pipeline",                      "← Listeye Dön"),
    ("de_btn_save",         "Save Updates",                            "Güncellemeleri Kaydet"),
    ("de_btn_delete",       "Delete Deal",                             "İşi Sil"),
    ("de_confirm_delete",   "Are you sure you want to delete this deal?",
                            "Bu fırsatı silmek istediğinize emin misiniz?"),
    ("de_company",          "Company",                                 "Firma"),
    ("de_contact",          "Contact",                                 "İletişim"),
    ("de_deal_size",        "Deal Size",                               "İş Büyüklüğü"),
    ("de_pricing",          "Pricing P.A.",                            "Fiyat Beklentisi"),
    ("de_currency",         "Currency",                                "Döviz Cinsi"),
    ("de_status",           "Status",                                  "Durum"),
    ("de_deal_type",        "Deal Type",                               "İş Tipi"),
    ("de_notes",            "Notes",                                   "Notlar"),
    ("de_created",          "Created At",                              "Oluşturulma"),
    ("de_no_notes",         "No notes provided.",                      "Not eklenmemiş."),

    # ─── Customer Edit ── Financial info ───
    ("ce_title",            "Edit Customer Profile",                   "Müşteri Profilini Düzenle"),
    ("ce_fin_info",         "Financial Information (Internal)",         "Finansal Bilgiler (İç Sistem)"),
    ("ce_fin_desc",         "These fields reflect core banking data and are read-only.",
                            "Bu alanlar temel bankacılık verilerini gösterir ve salt okunurdur."),
    ("ce_btn_save",         "Save Updates",                            "Güncellemeleri Kaydet"),
]


def seed():
    with app.app_context():
        try:
            conn = get_db()
        except Exception as e:
            print(f"Cannot connect to DB: {e}")
            return

        upsert_sql = """
            MERGE INTO BOA.ZZZ.Dictionary AS target
            USING (SELECT ? AS Id, ? AS LanguageId, ? AS Description) AS source
                ON target.Id = source.Id AND target.LanguageId = source.LanguageId
            WHEN NOT MATCHED THEN
                INSERT (Id, LanguageId, Description)
                VALUES (source.Id, source.LanguageId, source.Description);
        """

        inserted = 0
        for key_id, en_val, tr_val in ENTRIES:
            try:
                conn.execute(upsert_sql, (key_id, 0, en_val))
                conn.execute(upsert_sql, (key_id, 1, tr_val))
                inserted += 1
            except Exception as e:
                print(f"  SKIP {key_id}: {e}")

        conn.commit()
        conn.close()
        print(f"Done — processed {inserted} dictionary keys (EN + TR)")


if __name__ == "__main__":
    seed()
