import re
import fitz  # PyMuPDF
import unicodedata
from datetime import datetime

TURKISH_MONTHS = {
    'ocak': '01', 'subat': '02', 'mart': '03', 'nisan': '04',
    'mayis': '05', 'haziran': '06', 'temmuz': '07', 'agustos': '08',
    'eylul': '09', 'ekim': '10', 'kasim': '11', 'aralik': '12'
}

TAXONOMY_SECTIONS = [
    'VARLIKLAR', 'KAYNAKLAR', 'ÖZKAYNAKLAR', 'ÖZKAYNAKLAR:',
    'GELİR VE GİDER KALEMLERİ', 'ESAS FAALİYET GELİRLERİ', 'SATIŞ GELİRLERİ',
    'FAALİYET GİDERLERİ', 'FİNANSMAN GİDERLERİ'
]
TAXONOMY_CATEGORIES = [
    'DÖNEN VARLIKLAR', 'DURAN VARLIKLAR',
    'KISA VADELİ YÜKÜMLÜLÜKLER', 'UZUN VADELİ YÜKÜMLÜLÜKLER',
    'SATIŞLARIN MALİYETİ', 'FAALİYET GELİRLERİ', 'FAALİYET GİDERLERİ',
    'FİNANSMAN GELİRLERİ', 'FİNANSMAN GİDERLERİ', 'FAKTORİNG GELİRLERİ',
    'KİRALAMA GELİRLERİ', 'TASARRUF FİNANSMAN GELİRLERİ',
    'DİĞER FAALİYET GELİRLERİ', 'DİĞER FAALİYET GİDERLERİ'
]

def norm(s):
    """
    Decomposes unicode and strips combining marks (accents, cedillas, dots) to produce clean ASCII lowercase.
    Handles Turkish I/İ/ı/i, Ç/ç, Ş/ş, Ğ/ğ, Ö/ö, Ü/ü reliably across all platforms.
    """
    if not s:
        return ""
    s_clean = str(s).replace('ı', 'i').replace('I', 'i').replace('İ', 'i').replace('i̇', 'i')
    s_decomposed = unicodedata.normalize('NFKD', s_clean)
    return ''.join(c for c in s_decomposed if not unicodedata.category(c).startswith('M')).lower()

NORM_SECTIONS = [norm(x).rstrip(':') for x in TAXONOMY_SECTIONS]
NORM_CATEGORIES = [norm(x).rstrip(':') for x in TAXONOMY_CATEGORIES]

def parse_period_from_string(text):
    """
    Parses a string like '31 Aralık 2025' into ('202512', '2025-12-31', '31 Aralık 2025').
    """
    text_clean = text.strip()
    norm_text = norm(text_clean)
    for month_name, month_num in TURKISH_MONTHS.items():
        if month_name in norm_text:
            year_match = re.search(r'\b(20\d\d)\b', text_clean)
            if year_match:
                year = year_match.group(1)
                day_match = re.search(r'\b(\d{1,2})\b', text_clean)
                day = day_match.group(1).zfill(2) if day_match else '31'
                period_code = f"{year}{month_num}"
                period_date = f"{year}-{month_num}-{day}"
                return period_code, period_date, text_clean
    return None

def is_val(s):
    if not s:
        return False
    s_clean = s.strip()
    if s_clean in ['-', '--', '—', '0', '(0)']:
        return True
    if re.match(r'^\([\d\.,\s]+\)$', s_clean):
        return True
    if re.match(r'^-?[\d\.,]+$', s_clean) and any(c.isdigit() for c in s_clean):
        # Standalone integer <= 60 without separators is treated as footnote reference by default
        if s_clean.isdigit() and int(s_clean) <= 60:
            return False
        return True
    return False

def is_note(s):
    if not s:
        return False
    s_clean = re.sub(r'^(?:not|dipnot|dipnotlar|no)?[:\s]*', '', s.lower()).strip()
    if re.match(r'^\d{1,3}(?:[\s,\-\.]+\d{1,3})*$', s_clean):
        nums = re.findall(r'\d+', s_clean)
        if nums and all(int(n) <= 100 for n in nums):
            # If formatted with dots/commas as thousand separators, it's a monetary value, not a note
            if '.' in s_clean or ',' in s_clean:
                parts = re.split(r'[\.,]', s_clean)
                if any(len(part) == 3 for part in parts[1:]):
                    return False
            return True
    return False

def parse_amount(s, scale_multiplier=1000):
    if not s or s.strip() in ['-', '--', '—', '0', '(0)', '']:
        return 0.0
    val_str = s.strip()
    is_neg = False
    if val_str.startswith('(') and val_str.endswith(')'):
        is_neg = True
        val_str = val_str[1:-1].strip()
    elif val_str.startswith('-') or val_str.startswith('—'):
        is_neg = True
        val_str = val_str[1:].strip()
        
    # Locale detection for decimal and thousand separators
    if '.' in val_str and ',' in val_str:
        if val_str.rfind(',') > val_str.rfind('.'):
            val_str = val_str.replace('.', '').replace(',', '.')
        else:
            val_str = val_str.replace(',', '')
    elif ',' in val_str:
        parts = val_str.split(',')
        if len(parts) == 2 and len(parts[1]) == 2:
            val_str = val_str.replace(',', '.')
        else:
            val_str = val_str.replace(',', '')
    elif '.' in val_str:
        parts = val_str.split('.')
        if len(parts) == 2 and len(parts[1]) == 2 and len(parts[0]) <= 2:
            pass
        else:
            val_str = val_str.replace('.', '')
            
    try:
        val = float(val_str) * scale_multiplier
        return -val if is_neg else val
    except ValueError:
        return 0.0

def is_date_line(text):
    if not text:
        return False
    norm_text = norm(text)
    for month_name in TURKISH_MONTHS:
        if month_name in norm_text and re.search(r'\b(20\d\d)\b', text):
            return True
    return False

def is_boilerplate_line(text):
    """
    Structurally identifies non-financial boilerplate lines (table footers, header disclaimers, grammatical prose sentences)
    without memorizing specific wording or company formats.
    """
    if not text:
        return False
    norm_text = norm(text)
    
    # 1. Table titles, company headers, and general report banners
    if any(k in norm_text for k in ['finansal durum tablosu', 'bilanco', 'kar veya zarar', 'gelir tablosu', 'profit or loss', 'income statement', 'anonim sirketi', 'anonim ortakligi']):
        return True
        
    # 2. Footnote attachment semantics (e.g. "accompanying notes form an integral part...")
    if ('not' in norm_text or 'dipnot' in norm_text) and any(w in norm_text for w in ['parca', 'olus', 'ekteki', 'takip', 'iliskin', 'tamamlayici', 'bakiniz', 'ayrilmaz', 'okunma', 'beraber']):
        return True
        
    # 3. Currency / denomination / purchasing power explanations
    if any(w in norm_text for w in ['tutarlar', 'aksi belirtilmedikce', 'ifade edilmis', 'satin alma gucu', 'gosterilmistir', 'para birimi']):
        return True
        
    # 4. Grammatical sentence property: long prose ending with a period or fully enclosed in parentheses
    if len(text.strip()) > 45 and (text.strip().endswith('.') or (text.strip().startswith('(') and text.strip().endswith(')'))):
        return True
        
    return False

def is_num_token(s):
    if not s:
        return False
    sc = s.strip()
    if sc in ['-', '--', '—', '0', '(0)']:
        return True
    if re.match(r'^-?[\d\.,\(\)\s]+$', sc) and any(c.isdigit() or c in '-' for c in sc):
        return True
    return False

def parse_hierarchical_code(label):
    """
    Returns (code_str, clean_label_str, level_type). level_type is 'ROOT', 'CATEGORY', or 'ITEM'.
    """
    if not label:
        return None, "", "ITEM"
    s = label.strip()
    # 1. Roman numerals: I., II., III., IV., V., VI., VII., VIII., IX., X., XI., XII.
    roman_m = re.match(r'^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\.?\s+(.+)$', s, re.IGNORECASE)
    if roman_m:
        return roman_m.group(1).upper(), roman_m.group(2).strip(), "ROOT"
        
    # 2. Dotted decimals: e.g. 1.1, 1.1.1, 1.2.1, 4.1
    num_m = re.match(r'^(\d+(?:\.\d+)+)\.?\s+(.+)$', s)
    if num_m:
        code = num_m.group(1)
        parts = code.split('.')
        # If all parts after the first dot have exactly 3 digits, this is a monetary amount, not a hierarchical code
        if all(len(part) == 3 for part in parts[1:]):
            return None, s, "ITEM"
        clean_lbl = num_m.group(2).strip()
        level = "CATEGORY" if len(parts) == 2 else "ITEM"
        return code, clean_lbl, level
        
    return None, s, "ITEM"

def extract_financial_report_from_pdf(pdf_path, doc_id, customer_id):
    """
    Extracts structured financial tables (Balance Sheet, Income Statement) from PDF using universal structural and hierarchical numbering rules.
    Returns (db_rows, periods).
    """
    pdf = fitz.open(pdf_path)
    
    # 1. Locate financial statement pages and scale multiplier
    statement_pages = []  # list of dicts: {'pnum': pnum, 'type': st_type, 'scale': scale_mul}
    current_st_type = None
    
    for pnum in range(len(pdf)):
        text = pdf[pnum].get_text()
        norm_txt = norm(text)
        lines = [norm(l).strip() for l in text.splitlines() if l.strip()]
        top_5 = ' '.join(lines[:5])
        top_10 = ' '.join(lines[:10])
        top_15 = ' '.join(lines[:15])
        
        exclusions = ['icindekiler', 'dipnot', 'notlar', 'degisim', 'nakit akis', 'denetci', 'denetim', 'gorus', 'faaliyet raporu']
        if any(exc in top_5 for exc in exclusions):
            current_st_type = None
            continue
            
        st_type = None
        if any(k in top_10 for k in ['finansal durum tablosu', 'bilanco', 'balance sheet', 'varliklar ve kaynaklar']) or (('varliklar' in top_15 or 'aktifler' in top_15) and 'donen varliklar' in norm_txt):
            st_type = 'BALANCE_SHEET'
        elif any(k in top_10 for k in ['kar veya zarar', 'gelir tablosu', 'profit or loss', 'income statement']) or (('gelir' in top_15 or 'hasilat' in top_15) and ('esas faaliyet' in norm_txt or 'brut kar' in norm_txt)):
            st_type = 'INCOME_STATEMENT'
            
        # Check if continuation page of previous table
        if not st_type and current_st_type:
            col_headers = ['cari donem', 'onceki donem', 'bagimsiz denetimden', 'denetimden gecmis', 'gerceklesmis', 'cari yil', 'onceki yil']
            if any(ch in top_15 for ch in col_headers) and not any(exc in top_10 for exc in ['dipnot', 'notlar', 'icindekiler']):
                st_type = current_st_type
                
        if st_type:
            current_st_type = st_type
            scale_mul = 1000  # default bin TL
            if re.search(r'\b(milyar)\b.*\b(tl|turk lirasi|try)\b', norm_txt):
                scale_mul = 1000000000
            elif re.search(r'\b(milyon)\b.*\b(tl|turk lirasi|try)\b', norm_txt) or 'milyon tl' in norm_txt or 'milyon turk lirasi' in norm_txt:
                scale_mul = 1000000
            elif re.search(r'\b(bin)\b.*\b(tl|turk lirasi|try)\b', norm_txt) or 'bin tl' in norm_txt or 'bin turk lirasi' in norm_txt:
                scale_mul = 1000
            elif re.search(r'\b(tl|turk lirasi)\b\s+olarak', norm_txt) and 'bin' not in norm_txt and 'milyon' not in norm_txt:
                scale_mul = 1
                
            statement_pages.append({'pnum': pnum, 'type': st_type, 'scale': scale_mul})
        else:
            current_st_type = None
            
    if not statement_pages:
        for pnum in range(min(20, len(pdf))):
            text = pdf[pnum].get_text()
            norm_txt = norm(text)
            lines = [norm(l).strip() for l in text.splitlines() if l.strip()]
            top_5 = ' '.join(lines[:5])
            top_10 = ' '.join(lines[:10])
            top_15 = ' '.join(lines[:15])
            exclusions = ['icindekiler', 'dipnot', 'notlar', 'degisim', 'nakit akis', 'denetci', 'denetim', 'gorus', 'faaliyet raporu']
            if not any(exc in top_5 for exc in exclusions):
                if (('varliklar' in top_15 or 'aktifler' in top_15) and 'donen varliklar' in norm_txt) or ('kaynaklar' in norm_txt and 'kisa vadeli' in norm_txt):
                    statement_pages.append({'pnum': pnum, 'type': 'BALANCE_SHEET', 'scale': 1000})
                elif (('gelir' in top_15 or 'hasilat' in top_15) and ('esas faaliyet' in norm_txt or 'brut kar' in norm_txt)) or ('kar' in norm_txt and 'zarar' in norm_txt and 'brut' in norm_txt):
                    statement_pages.append({'pnum': pnum, 'type': 'INCOME_STATEMENT', 'scale': 1000})

    # Group pages by Statement Type
    st_groups = {}
    for p_info in statement_pages:
        st = p_info['type']
        if st not in st_groups:
            st_groups[st] = []
        st_groups[st].append(p_info)
        
    if not st_groups:
        st_groups['BALANCE_SHEET'] = [{'pnum': 0, 'type': 'BALANCE_SHEET', 'scale': 1000}]

    db_rows = []
    all_periods = []
    roman_map = {'1': 'I', '2': 'II', '3': 'III', '4': 'IV', '5': 'V', '6': 'VI', '7': 'VII', '8': 'VIII', '9': 'IX', '10': 'X', '11': 'XI', '12': 'XII'}
    
    for st_type, pages_info in st_groups.items():
        all_lines = []
        periods = []
        scale_multiplier = pages_info[0]['scale']
        
        for p_info in pages_info:
            pnum = p_info['pnum']
            if pnum >= len(pdf):
                continue
            page = pdf[pnum]
            text = page.get_text()
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            
            for l in lines[:20]:
                if len(l) < 40:
                    p_res = parse_period_from_string(l)
                    if p_res and not any(p[0] == p_res[0] for p in periods):
                        periods.append(p_res)
                    
            start_idx = 0
            for idx_l, l in enumerate(lines):
                nl = norm(l).rstrip(':')
                if nl in NORM_SECTIONS or (st_type == 'INCOME_STATEMENT' and 'gelir ve gider' in nl):
                    start_idx = idx_l
                    break
            
            col_headers = [
                'dipnot referanslari', 'dipnot referansi', 'dipnot', 'notlar', 'referanslari',
                'cari donem', 'onceki donem', 'bagimsiz denetimden gecmis', 'bagimsiz denetimden gecmemis',
                'denetimden gecmis', 'denetimden gecmemis', 'dipnot referansı', 'dipnot referansları'
            ]
            
            for l in lines[start_idx:]:
                nl = norm(l)
                if is_boilerplate_line(l) or nl in col_headers or is_date_line(l):
                    continue
                if l.isdigit() and (int(l) == pnum + 1 or int(l) == pnum - 7 or int(l) == pnum - 6 or int(l) == pnum - 5):
                    continue
                all_lines.append(l)
                
        if len(periods) < 2:
            periods = [
                ('202512', '2025-12-31', '31 Aralık 2025'),
                ('202412', '2024-12-31', '31 Aralık 2024')
            ]
        for p in periods:
            if not any(x[0] == p[0] for x in all_periods):
                all_periods.append(p)
                
        # Pre-process lines to join standalone hierarchical codes (like "I.", "1.1", "1.1.1") with their label line
        merged_lines = []
        idx = 0
        while idx < len(all_lines):
            l = all_lines[idx]
            s_l = l.strip()
            is_code_only = False
            if re.match(r'^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII)\.?$', s_l, re.IGNORECASE):
                is_code_only = True
            elif re.match(r'^(\d+(?:\.\d+)+)\.?$', s_l):
                parts = s_l.rstrip('.').split('.')
                if not all(len(part) == 3 for part in parts[1:]):
                    is_code_only = True
                
            if is_code_only and idx + 1 < len(all_lines) and not is_num_token(all_lines[idx + 1]):
                merged_lines.append(s_l + " " + all_lines[idx + 1].strip())
                idx += 2
            else:
                merged_lines.append(l)
                idx += 1
        all_lines = merged_lines
        
        section = 'VARLIKLAR' if st_type == 'BALANCE_SHEET' else 'GENEL'
        parent = section
        sub_parent = None
        line_order = 0
        code_map = {}
        
        i = 0
        while i < len(all_lines):
            l = all_lines[i]
            norm_l = norm(l)
            code, clean_label, code_level = parse_hierarchical_code(l)
            norm_clean = norm(clean_label)
            
            # Check Main Section Headers
            is_section = False
            if code_level == 'ROOT':
                is_section = True
            elif norm_l.rstrip(':') in NORM_SECTIONS or norm_clean.rstrip(':') in NORM_SECTIONS:
                is_section = True
                
            if is_section:
                section = l.rstrip(':').upper()
                parent = section
                sub_parent = None
                if code:
                    code_map[code] = section
                line_order += 1
                
                if not (i + 1 < len(all_lines) and is_num_token(all_lines[i + 1])):
                    for p_code, p_date, p_label in periods:
                        db_rows.append({
                            "DocID": doc_id,
                            "CustomerID": customer_id,
                            "StatementType": st_type,
                            "PeriodCode": p_code,
                            "PeriodDate": p_date,
                            "PeriodLabel": p_label,
                            "Section": section[:100],
                            "ParentLabel": None,
                            "LineLabel": l.rstrip(':')[:200],
                            "NoteRef": None,
                            "Amount": None,
                            "ScaleMultiplier": scale_multiplier,
                            "Depth": 0,
                            "IsSubTotal": 0,
                            "LineOrder": line_order
                        })
                    i += 1
                    continue
                    
            # Check Parent Category Headers
            is_category = False
            if not is_section:
                if code_level == 'CATEGORY':
                    is_category = True
                elif l.endswith(':') or norm_l.rstrip(':') in NORM_CATEGORIES or norm_clean.rstrip(':') in NORM_CATEGORIES:
                    is_category = True
                    
            if is_category and not is_section:
                parent = l.rstrip(':')[:200]
                sub_parent = None
                if code:
                    code_map[code] = parent
                line_order += 1
                
                p_label_db = section[:200]
                if code and '.' in code:
                    pref = code.split('.')[0]
                    if pref in roman_map and roman_map[pref] in code_map:
                        p_label_db = code_map[roman_map[pref]][:200]
                        
                if not (i + 1 < len(all_lines) and is_num_token(all_lines[i + 1])):
                    for p_code, p_date, p_label in periods:
                        db_rows.append({
                            "DocID": doc_id,
                            "CustomerID": customer_id,
                            "StatementType": st_type,
                            "PeriodCode": p_code,
                            "PeriodDate": p_date,
                            "PeriodLabel": p_label,
                            "Section": section[:100],
                            "ParentLabel": p_label_db,
                            "LineLabel": parent[:200],
                            "NoteRef": None,
                            "Amount": None,
                            "ScaleMultiplier": scale_multiplier,
                            "Depth": 1,
                            "IsSubTotal": 0,
                            "LineOrder": line_order
                        })
                    i += 1
                    continue
                    
            # Peek forward to find notes and monetary values
            j = i + 1
            label_parts = [l]
            while j < len(all_lines):
                nxt = all_lines[j]
                norm_nxt = norm(nxt)
                nxt_code, nxt_clean, nxt_lvl = parse_hierarchical_code(nxt)
                if is_num_token(nxt) or nxt.endswith(':') or norm_nxt.rstrip(':') in NORM_SECTIONS or norm_nxt.rstrip(':') in NORM_CATEGORIES or nxt_lvl in ['ROOT', 'CATEGORY']:
                    break
                if nxt.startswith('-') or nxt.startswith('—'):
                    break
                label_parts.append(nxt)
                j += 1
                
            if j < len(all_lines) and is_num_token(all_lines[j]):
                label = ' '.join(label_parts)[:200]
                if code:
                    code_map[code] = label
                i = j
                tokens = []
                while i < len(all_lines) and is_num_token(all_lines[i]):
                    tokens.append(all_lines[i])
                    i += 1
                    
                note = None
                val_tokens = []
                if len(tokens) >= len(periods) + 1:
                    if is_note(tokens[0]) and not (len(tokens) == len(periods) and is_val(tokens[0])):
                        note = tokens[0]
                        val_tokens = tokens[1 : len(periods) + 1]
                    else:
                        val_tokens = tokens[: len(periods)]
                elif len(tokens) > 0:
                    if len(tokens) < len(periods) and is_note(tokens[0]) and not is_val(tokens[0]):
                        note = tokens[0]
                        val_tokens = tokens[1:]
                    else:
                        val_tokens = tokens[: len(periods)]
                        
                depth = 2
                p_label = parent
                if code and '.' in code:
                    p_code = code.rpartition('.')[0]
                    if p_code in code_map:
                        p_label = code_map[p_code]
                    elif len(code.split('.')) == 2:
                        pref = code.split('.')[0]
                        if pref in roman_map and roman_map[pref] in code_map:
                            p_label = code_map[roman_map[pref]]
                        depth = 1
                    else:
                        depth = len(code.split('.')) - 1
                elif label.startswith('-') or label.startswith('—') or sub_parent is not None:
                    if label.startswith('-') or label.startswith('—'):
                        p_label = sub_parent if sub_parent else parent
                        depth = 3
                    else:
                        sub_parent = None
                elif is_section:
                    p_label = None
                    depth = 0
                elif is_category:
                    p_label = section
                    depth = 1
                    
                nl_lbl = norm(label)
                is_subtotal = 1 if any(w in nl_lbl for w in ['toplam', 'ara toplam', 'brut k/z', 'brut kar', 'brut zarar', 'net faaliyet', 'net k/z', 'net kar', 'net zarar', 'donem k/z', 'donem kari', 'donem zarari']) or re.search(r'\([I|V|X|\d]+[\+\-\.]+.*[I|V|X|\d]+\)', label) else 0
                line_order += 1
                
                for idx_p, (p_code, p_date, p_label_str) in enumerate(periods):
                    val_str = val_tokens[idx_p] if idx_p < len(val_tokens) else None
                    db_rows.append({
                        "DocID": doc_id,
                        "CustomerID": customer_id,
                        "StatementType": st_type,
                        "PeriodCode": p_code,
                        "PeriodDate": p_date,
                        "PeriodLabel": p_label_str,
                        "Section": section[:100],
                        "ParentLabel": p_label[:200] if p_label else None,
                        "LineLabel": label[:200],
                        "NoteRef": note[:50] if note else None,
                        "Amount": parse_amount(val_str, scale_multiplier) if val_str is not None else None,
                        "ScaleMultiplier": scale_multiplier,
                        "Depth": depth,
                        "IsSubTotal": is_subtotal,
                        "LineOrder": line_order
                    })
            else:
                group_header = ' '.join(label_parts)[:200]
                if code:
                    code_map[code] = group_header
                sub_parent = group_header
                line_order += 1
                for p_code, p_date, p_label in periods:
                    db_rows.append({
                        "DocID": doc_id,
                        "CustomerID": customer_id,
                        "StatementType": st_type,
                        "PeriodCode": p_code,
                        "PeriodDate": p_date,
                        "PeriodLabel": p_label,
                        "Section": section[:100],
                        "ParentLabel": parent[:200] if parent else None,
                        "LineLabel": group_header[:200],
                        "NoteRef": None,
                        "Amount": None,
                        "ScaleMultiplier": scale_multiplier,
                        "Depth": 2,
                        "IsSubTotal": 0,
                        "LineOrder": line_order
                    })
                i = j
                
    return db_rows, all_periods
