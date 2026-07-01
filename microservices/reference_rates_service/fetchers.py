import logging
import requests
from datetime import datetime, date, timedelta
from typing import Dict, Any, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from microservices.reference_rates_service.models import ReferenceRateJournal
from microservices.reference_rates_service.config import (
    NY_FED_SOFR_PRIMARY_URL,
    NY_FED_SOFR_SEARCH_URL,
    ECB_SDMX_EURIBOR_PRIMARY_URL,
    ECB_SDMX_EURIBOR_FALLBACK_URL
)

logger = logging.getLogger("reference_rates_fetcher")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def insert_ignore_rate(session: Session, effective_date: date, rate_type: str, rate_value: float) -> bool:
    """
    Implements immutable ledger 'Insert Ignore' / 'Upsert' logic.
    If a record with (effective_date, rate_type) already exists, it is ignored without error.
    Never performs UPDATE operations on existing historical values.
    
    Returns True if a new record was inserted, False if ignored.
    """
    # Check if record already exists in ledger
    existing = session.query(ReferenceRateJournal).filter_by(
        effective_date=effective_date,
        rate_type=rate_type
    ).first()
    
    if existing:
        logger.debug(f"[Ignore] Rate {rate_type} for date {effective_date} already exists in ledger ({existing.rate_value}).")
        return False

    try:
        journal_entry = ReferenceRateJournal(
            effective_date=effective_date,
            rate_type=rate_type,
            rate_value=round(float(rate_value), 6),
            fetched_at=datetime.utcnow()
        )
        session.add(journal_entry)
        session.commit()
        logger.info(f"[Insert] Added new reference rate: {rate_type} on {effective_date} -> {rate_value}%")
        return True
    except IntegrityError:
        # Catch concurrent race condition duplicates gracefully
        session.rollback()
        logger.debug(f"[IntegrityError Ignore] Duplicate detected for {rate_type} on {effective_date}.")
        return False
    except Exception as e:
        session.rollback()
        logger.error(f"[Database Error] Failed to insert {rate_type} for {effective_date}: {str(e)}")
        return False


def fetch_sofr_rates(session: Session) -> Tuple[int, int, List[str]]:
    """
    Fetches official SOFR and Federal Reserve reference rates from the New York Fed REST API.
    Covers: SOFR_ON, SOFR_30D_AVG, SOFR_90D_AVG, SOFR_180D_AVG, SOFR_INDEX, EFFR, OBFR, TGCR, BGCR.
    Returns (inserted_count, ignored_count, errors_list).
    """
    inserted = 0
    ignored = 0
    errors = []

    # 1. Fetch historical 50-day series for US Federal Reserve rates
    us_history_urls = [
        ("SOFR_ON", NY_FED_SOFR_PRIMARY_URL),
        ("EFFR", "https://markets.newyorkfed.org/api/rates/unsecured/effr/last/50.json"),
        ("OBFR", "https://markets.newyorkfed.org/api/rates/unsecured/obfr/last/50.json"),
        ("TGCR", "https://markets.newyorkfed.org/api/rates/secured/tgcr/last/50.json"),
        ("BGCR", "https://markets.newyorkfed.org/api/rates/secured/bgcr/last/50.json")
    ]
    for rate_code, url in us_history_urls:
        try:
            logger.info(f"Fetching NY Fed history for {rate_code} from: {url}")
            res = requests.get(url, timeout=15)
            if res.status_code == 200:
                for item in res.json().get("refRates", []):
                    date_str = item.get("effectiveDate")
                    val_num = item.get("percentRate")
                    if date_str and val_num is not None:
                        eff_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                        if insert_ignore_rate(session, eff_date, rate_code, float(val_num)):
                            inserted += 1
                        else:
                            ignored += 1
        except Exception as e:
            err_msg = f"NY Fed {rate_code} history error: {str(e)}"
            logger.error(err_msg)
            errors.append(err_msg)

    # 2. Fetch historical SOFRAI (SOFR Averages & Index)
    sofrai_url = "https://markets.newyorkfed.org/api/rates/secured/sofrai/last/50.json"
    try:
        logger.info(f"Fetching NY Fed SOFR Averages & Index from: {sofrai_url}")
        res = requests.get(sofrai_url, timeout=15)
        if res.status_code == 200:
            for item in res.json().get("refRates", []):
                date_str = item.get("effectiveDate")
                if not date_str:
                    continue
                eff_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                
                avg_map = {
                    "SOFR_30D_AVG": item.get("average30day"),
                    "SOFR_90D_AVG": item.get("average90day"),
                    "SOFR_180D_AVG": item.get("average180day"),
                    "SOFR_INDEX": item.get("index")
                }
                for rate_code, val_num in avg_map.items():
                    if val_num is not None:
                        if insert_ignore_rate(session, eff_date, rate_code, float(val_num)):
                            inserted += 1
                        else:
                            ignored += 1
    except Exception as e:
        err_msg = f"NY Fed SOFRAI error: {str(e)}"
        logger.error(err_msg)
        errors.append(err_msg)

    return inserted, ignored, errors


def fetch_euribor_rates(session: Session) -> Tuple[int, int, List[str]]:
    """
    Fetches official EURIBOR tenors (1W, 1M, 3M, 6M, 12M) from Deutsche Bundesbank Official Statistical CSV API.
    Returns (inserted_count, ignored_count, errors_list).
    """
    inserted = 0
    ignored = 0
    errors = []

    tenor_map = {
        "W01": "EURIBOR_1W",
        "M01": "EURIBOR_1M",
        "M03": "EURIBOR_3M",
        "M06": "EURIBOR_6M",
        "M12": "EURIBOR_12M"
    }
    headers = {"User-Agent": "ReferenceRatesIngestionService/1.0"}

    for bb_code, rate_code in tenor_map.items():
        url = f"https://www.bundesbank.de/statistic-rmi/StatisticDownload?tsId=BBIG1.D.D0.EUR.MMKT.EURIBOR.{bb_code}.BID._Z&mode=its&format=csv"
        try:
            logger.info(f"Fetching EURIBOR {rate_code} from Bundesbank...")
            res = requests.get(url, headers=headers, timeout=15)
            if res.status_code == 200:
                content = res.content.decode("utf-8-sig", errors="ignore")
                lines = [l.strip() for l in content.split("\n") if l.strip() and not l.startswith("#")]
                # Process last 30 daily entries
                for line in lines[-40:]:
                    parts = line.split(";")
                    if len(parts) >= 2 and parts[0] and parts[1]:
                        date_str = parts[0].strip()
                        val_str = parts[1].strip()
                        if len(date_str) == 10 and date_str[4] == "-" and date_str[7] == "-" and val_str != ".":
                            try:
                                eff_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                                rate_val = round(float(val_str.replace(",", ".")), 6)
                                if insert_ignore_rate(session, eff_date, rate_code, rate_val):
                                    inserted += 1
                                else:
                                    ignored += 1
                            except Exception:
                                pass
        except Exception as e:
            err_msg = f"Bundesbank EURIBOR {rate_code} fetch error: {str(e)}"
            logger.error(err_msg)
            errors.append(err_msg)

    return inserted, ignored, errors


def run_all_fetchers(session: Session) -> Dict[str, Any]:
    """
    Orchestrates ingestion across all supported official central bank APIs (14 official tenors from NY Fed & Bundesbank).
    Returns summary statistics of inserted, ignored, and error records.
    """
    logger.info("--- Starting Financial Reference Rates Ingestion Cycle (14 Official Benchmarks) ---")
    s_inst, s_ign, s_err = fetch_sofr_rates(session)
    e_inst, e_ign, e_err = fetch_euribor_rates(session)
    
    tot_inst = s_inst + e_inst
    tot_ign = s_ign + e_ign
    tot_err = s_err + e_err

    summary = {
        "success": len(tot_err) == 0,
        "records_inserted": tot_inst,
        "records_ignored": tot_ign,
        "details": {
            "sofr_group": {"inserted": s_inst, "ignored": s_ign, "errors": s_err},
            "euribor_group": {"inserted": e_inst, "ignored": e_ign, "errors": e_err}
        },
        "errors": tot_err
    }
    logger.info(f"--- Ingestion Complete | Inserted: {summary['records_inserted']} | Ignored: {summary['records_ignored']} ---")
    return summary
