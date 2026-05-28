"""
Amazon Product Scraper — Streamlit GUI
Run with:  streamlit run amazon_scraper_app.py
"""

import re
import time
import random
import datetime
import io
import urllib.parse
from urllib.parse import unquote

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
import streamlit as st
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import WebDriverException, TimeoutException

# ─────────────────────────────────────────────────────────────────────────────
# CONSTANTS
# ─────────────────────────────────────────────────────────────────────────────

AMAZON_DOMAINS = {
    "amazon.com":      "United States",
    "amazon.co.uk":    "United Kingdom",
    "amazon.de":       "Germany",
    "amazon.co.jp":    "Japan",
    "amazon.in":       "India",
    "amazon.fr":       "France",
    "amazon.es":       "Spain",
    "amazon.it":       "Italy",
    "amazon.ca":       "Canada",
    "amazon.com.mx":   "Mexico",
    "amazon.com.br":   "Brazil",
    "amazon.com.au":   "Australia",
    "amazon.nl":       "Netherlands",
    "amazon.se":       "Sweden",
    "amazon.pl":       "Poland",
    "amazon.sg":       "Singapore",
    "amazon.com.tr":   "Turkey",
    "amazon.ae":       "United Arab Emirates",
    "amazon.sa":       "Saudi Arabia",
    "amazon.com.be":   "Belgium",
    "amazon.eg":       "Egypt",
}

DOMAIN_TO_CCY = {
    "amazon.com":      "USD",
    "amazon.co.uk":    "GBP",
    "amazon.de":       "EUR",
    "amazon.co.jp":    "JPY",
    "amazon.in":       "INR",
    "amazon.fr":       "EUR",
    "amazon.es":       "EUR",
    "amazon.it":       "EUR",
    "amazon.ca":       "CAD",
    "amazon.com.mx":   "MXN",
    "amazon.com.br":   "BRL",
    "amazon.com.au":   "AUD",
    "amazon.nl":       "EUR",
    "amazon.se":       "SEK",
    "amazon.pl":       "PLN",
    "amazon.sg":       "SGD",
    "amazon.com.tr":   "TRY",
    "amazon.ae":       "AED",
    "amazon.sa":       "SAR",
    "amazon.com.be":   "EUR",
    "amazon.eg":       "EGP",
}

FX_TO_USD = {
    "USD": 1.0,    "EUR": 1.167,  "GBP": 1.364,
    "CAD": 0.731,  "AUD": 0.6495, "JPY": 0.006883,
    "INR": 0.0114, "SEK": 0.1051, "PLN": 0.2679,
    "TRY": 0.0197, "AED": 0.2723, "SAR": 0.2667,
    "EGP": 0.0194, "SGD": 0.7857, "BRL": 0.1696,
    "MXN": 0.0530,
}

ACCESSORY_KEYWORDS = [
    "case", "mount", "battery", "charger", "stand",
    "cable", "pouch", "holder", "adapter",
]

PALETTE = ["#4C72B0", "#DD8452", "#55A868", "#C44E52", "#8172B3", "#937860"]

# ── Default postal codes for "Deliver to" location per domain ────────────────
# These are typical central / capital city postcodes for each marketplace.
# You can override them in the UI.
DOMAIN_DEFAULT_POSTCODE = {
    "amazon.com":      "10001",     # New York, NY
    "amazon.co.uk":    "W1A 1AA",   # London
    "amazon.de":       "10115",     # Berlin
    "amazon.co.jp":    "100-0001",  # Tokyo
    "amazon.in":       "110001",    # New Delhi
    "amazon.fr":       "75001",     # Paris
    "amazon.es":       "28001",     # Madrid
    "amazon.it":       "00118",     # Rome
    "amazon.ca":       "M5H 2N2",   # Toronto
    "amazon.com.mx":   "06600",     # Mexico City
    "amazon.com.br":   "01310-100", # São Paulo
    "amazon.com.au":   "2000",      # Sydney
    "amazon.nl":       "1011 AB",   # Amsterdam
    "amazon.se":       "111 20",    # Stockholm
    "amazon.pl":       "00-001",    # Warsaw
    "amazon.sg":       "048583",    # Singapore
    "amazon.com.tr":   "34000",     # Istanbul
    "amazon.ae":       "00000",     # Dubai (AE has no postal codes; use 00000)
    "amazon.sa":       "11564",     # Riyadh
    "amazon.com.be":   "1000",      # Brussels
    "amazon.eg":       "11511",     # Cairo
}

# ─────────────────────────────────────────────────────────────────────────────
# PARSING HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def normalize_ws(s):
    return re.sub(r"\s+", " ", s or "").strip()

def sanitize_for_path(text):
    return "".join(c if c.isalnum() or c in "-_." else "_" for c in text)[:150]

def extract_currency_dynamic(price_str):
    if not price_str:
        return ""
    match = re.search(r"(\d+(?:[.,]\d+)*)", price_str)
    if not match:
        return ""
    start, end = match.span()
    prefix = price_str[:start].strip()
    return prefix if prefix else price_str[end:].strip()

def parse_price_to_float(price_text):
    if not price_text:
        return None
    s = price_text.replace("\u00a0", " ").strip()
    m = re.search(r"(\d[\d.,]*)", s)
    if not m:
        return None
    num = m.group(1)
    if "." in num and "," in num:
        if num.rfind(",") > num.rfind("."):
            num = num.replace(".", "").replace(",", ".")
        else:
            num = num.replace(",", "")
    elif "," in num:
        parts = num.split(",")
        num = num.replace(",", ".") if len(parts[-1]) in (1, 2) else num.replace(",", "")
    try:
        return float(num)
    except ValueError:
        return None

def convert_to_usd(amount, ccy_code):
    if amount is None:
        return None
    rate = FX_TO_USD.get(ccy_code)
    return round(amount * rate, 2) if rate else None

def classify_product(title, rules, search_term):
    t = (title or "").lower()
    for rule in rules:
        if any(exc in t for exc in rule["exclude"]):
            continue
        if any(inc in t for inc in rule["include"]):
            return rule["type"]
    if any(acc in t for acc in ACCESSORY_KEYWORDS):
        return f"{search_term.title()} (Accessory)"
    return f"{search_term.title()} (Other)"

def parse_kw(text):
    return [x.strip().lower() for x in (text or "").split(",") if x.strip()]

# ─────────────────────────────────────────────────────────────────────────────
# EXTRACTION
# ─────────────────────────────────────────────────────────────────────────────

def extract_title_and_link(card, domain):
    a = card.select_one('[data-cy="title-recipe"] a, h2 a.a-link-normal, h2 a')
    if not a:
        return None, None
    title = normalize_ws(a.get_text())
    href  = a.get("href", "")
    dp    = re.search(r"(/dp/[A-Z0-9]{8,12})", unquote(href))
    if dp:
        href = f"https://{domain}{dp.group(1)}"
    elif href.startswith("/"):
        href = f"https://{domain}{href}"
    return title, href

def extract_primary_price_text(card):
    for price_el in card.select(".a-price"):
        parent_classes = price_el.parent.get("class", []) if price_el.parent else []
        if "a-text-price" in parent_classes:
            continue
        off = price_el.select_one(".a-offscreen")
        if off:
            return off.get_text().replace("\u00a0", " ").strip()
    return ""

def extract_rating(card):
    alt = card.select_one(".a-icon-alt")
    if alt:
        m = re.search(r"(\d+(?:\.\d+)?)", alt.get_text())
        return float(m.group(1)) if m else None
    return None

def parse_html(html_source, domain, search_term, rules):
    soup  = BeautifulSoup(html_source, "html.parser")
    cards = soup.find_all(attrs={"data-asin": True},
                          class_=re.compile(r"\bs-result-item\b"))
    rows  = []
    for card in cards:
        title, link = extract_title_and_link(card, domain)
        if not title:
            continue
        price_text  = extract_primary_price_text(card)
        ccy_code    = DOMAIN_TO_CCY.get(domain)
        price_value = parse_price_to_float(price_text)
        rows.append({
            "product_type":   classify_product(title, rules, search_term),
            "search_term":    search_term,
            "origin_country": AMAZON_DOMAINS.get(domain, domain),
            "product_name":   title,
            "currency_code":  ccy_code,
            "currency":       extract_currency_dynamic(price_text),
            "price":          price_text,
            "price_value":    price_value,
            "price_usd":      convert_to_usd(price_value, ccy_code),
            "rating":         extract_rating(card),
            "link":           link,
        })
    return rows

# ─────────────────────────────────────────────────────────────────────────────
# SCRAPER
# ─────────────────────────────────────────────────────────────────────────────

def _js_click(driver, element):
    """Click via JavaScript — bypasses overlays and visibility issues."""
    driver.execute_script("arguments[0].click();", element)


def _js_set(driver, element, value):
    """Set an input value via JS and fire an input event so Amazon's JS notices."""
    driver.execute_script("arguments[0].value = '';",          element)
    driver.execute_script("arguments[0].value = arguments[1];", element, value)
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input', {bubbles:true}));", element)


def _dismiss_interstitial(driver):
    """
    Dismisses 'Continue shopping', cookie banners, or any full-page overlay.
    Tries each selector silently; returns True if something was dismissed.
    """
    INTERSTITIAL_SELECTORS = [
        # ── "Continue shopping" interstitial (confirmed live selector) ────────
        "button.a-button-text[alt='Continue shopping']",
        "button[type='submit'][alt='Continue shopping']",
        # ── Older / input-based variants ──────────────────────────────────────
        "input[value*='Continue shopping']",
        "input[value*='Continue'], input[value*='continue']",
        "a[href*='ref=cs_503_link']",
        # ── Cookie / GDPR banners ─────────────────────────────────────────────
        "#sp-cc-accept",
        "input[data-cel-widget='sp-cc-accept']",
        "[id*='cookie'] button.a-button-primary",
        "[id*='gdpr'] button.a-button-primary",
        # ── Generic modal footer button ───────────────────────────────────────
        ".a-popover-footer .a-button-primary input",
    ]
    for sel in INTERSTITIAL_SELECTORS:
        try:
            btn = WebDriverWait(driver, 2).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, sel)))
            _js_click(driver, btn)
            time.sleep(0.8)
            return True
        except (TimeoutException, WebDriverException):
            continue
    return False


def _click_confirm_close(driver):
    """
    Clicks the GLUXConfirmClose / Done button after a postcode is applied.
    Waits for it to become un-hidden first (Amazon reveals it asynchronously).
    """
    try:
        WebDriverWait(driver, 5).until(
            lambda d: "GLUX_Hidden" not in
            d.find_element(By.ID, "GLUXConfirmClose")
             .find_element(By.XPATH, "./ancestor::div[contains(@class,'GLUX')]")
             .get_attribute("class")
        )
    except (TimeoutException, WebDriverException):
        pass  # Best-effort — proceed anyway
    try:
        btn = WebDriverWait(driver, 4).until(
            EC.presence_of_element_located((By.ID, "GLUXConfirmClose")))
        _js_click(driver, btn)
        time.sleep(1.2)
    except (TimeoutException, WebDriverException):
        pass  # Popup may close automatically on some locales


# ── Domains that already show the correct local location — skip entirely ──────
SKIP_LOCATION_DOMAINS = {
    "amazon.ca",        # Balzac, Canada — already local
    "amazon.com.br",    # Brazil — already local
    "amazon.nl",        # Amsterdam — already local
    "amazon.se",        # Stockholm — already local
    "amazon.pl",        # Warsaw — already local
    "amazon.ae",        # Dubai — already local
    "amazon.sa",        # Riyadh — already local
    "amazon.com.be",    # Brussels — already local
}


def _set_location_standard(driver, postcode):
    """
    Standard GLUX flow used by most Amazon locales:
      type into #GLUXZipUpdateInput → Apply → Confirm/Done
    """
    zip_input = WebDriverWait(driver, 8).until(
        EC.presence_of_element_located((By.ID, "GLUXZipUpdateInput")))
    driver.execute_script("arguments[0].scrollIntoView(true);", zip_input)
    time.sleep(0.4)
    _js_set(driver, zip_input, postcode)
    time.sleep(0.6)

    apply_btn = WebDriverWait(driver, 6).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#GLUXZipUpdate input[type='submit']")))
    _js_click(driver, apply_btn)
    time.sleep(1.5)

    # Wait for confirmation section to appear (loses GLUX_Hidden class)
    try:
        WebDriverWait(driver, 5).until(
            lambda d: "GLUX_Hidden" not in
            d.find_element(By.ID, "GLUXZipConfirmationSection")
             .get_attribute("class"))
    except TimeoutException:
        pass

    _click_confirm_close(driver)


def _set_location_japan(driver, postcode):
    """
    Japan (amazon.co.jp) uses two separate inputs:
      #GLUXZipUpdateInput_0  — first 3 digits  (e.g. "100")
      #GLUXZipUpdateInput_1  — last  4 digits  (e.g. "0001")
    Postcode format in config: "100-0001"
    """
    # Split on hyphen; pad/trim defensively
    parts = postcode.replace(" ", "").split("-")
    part0 = parts[0][:3]  if len(parts) > 0 else ""
    part1 = parts[1][:4]  if len(parts) > 1 else ""

    inp0 = WebDriverWait(driver, 8).until(
        EC.presence_of_element_located((By.ID, "GLUXZipUpdateInput_0")))
    driver.execute_script("arguments[0].scrollIntoView(true);", inp0)
    time.sleep(0.4)
    _js_set(driver, inp0, part0)

    inp1 = WebDriverWait(driver, 6).until(
        EC.presence_of_element_located((By.ID, "GLUXZipUpdateInput_1")))
    _js_set(driver, inp1, part1)
    time.sleep(0.6)

    apply_btn = WebDriverWait(driver, 6).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR, "#GLUXZipUpdate input[type='submit']")))
    _js_click(driver, apply_btn)
    time.sleep(1.5)

    _click_confirm_close(driver)


def _set_location_australia(driver, postcode):
    """
    Australia (amazon.com.au) uses:
      #GLUXPostalCodeWithCity_PostalCodeInput  — 4-digit postcode
      Then a city dropdown appears → pick first option
      Then click Apply (input[type='submit'])
    """
    zip_input = WebDriverWait(driver, 8).until(
        EC.presence_of_element_located(
            (By.ID, "GLUXPostalCodeWithCity_PostalCodeInput")))
    driver.execute_script("arguments[0].scrollIntoView(true);", zip_input)
    time.sleep(0.4)
    _js_set(driver, zip_input, postcode)
    time.sleep(0.8)

    # Wait for the city dropdown to become available and click it
    city_dropdown_btn = WebDriverWait(driver, 6).until(
        EC.element_to_be_clickable(
            (By.CSS_SELECTOR,
             "[aria-label='Select your City'], "
             "#GLUXPostalCodeWithCity_CityValue, "
             "span.a-dropdown-prompt")))
    _js_click(driver, city_dropdown_btn)
    time.sleep(0.8)

    # Pick the first city in the dropdown list
    first_city = WebDriverWait(driver, 6).until(
        EC.element_to_be_clickable(
            (By.ID, "GLUXPostalCodeWithCity_DropdownList_0")))
    _js_click(driver, first_city)
    time.sleep(0.6)

    # Click Apply
    apply_btn = WebDriverWait(driver, 6).until(
        EC.presence_of_element_located(
            (By.CSS_SELECTOR,
             "#GLUXPostalCodeWithCity_SubmitButton input[type='submit'], "
             "input.a-button-input[type='submit']")))
    _js_click(driver, apply_btn)
    time.sleep(1.5)

    _click_confirm_close(driver)


# ── Per-domain routing table ──────────────────────────────────────────────────
_LOCATION_HANDLERS = {
    "amazon.co.jp":    _set_location_japan,
    "amazon.com.au":   _set_location_australia,
    # All other domains use _set_location_standard (default)
}


def set_delivery_location(driver, domain, postcode, log_fn):
    """
    Entry point: loads the domain homepage, dismisses any overlay,
    then routes to the correct location-setting handler for that domain.
    Domains in SKIP_LOCATION_DOMAINS are silently skipped.
    """
    # ── Skip domains that are already showing their local location ────────────
    if domain in SKIP_LOCATION_DOMAINS:
        log_fn(f"  ⏭️ `{domain}` already shows local location — skipping")
        return True

    try:
        # ── Load homepage & dismiss overlays ──────────────────────────────────
        driver.get(f"https://{domain}")
        time.sleep(random.uniform(1.5, 2.5))
        _dismiss_interstitial(driver)

        # ── Click "Deliver to" trigger ────────────────────────────────────────
        loc_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "#nav-global-location-popover-link")))
        _js_click(driver, loc_btn)
        time.sleep(1.2)

        # ── Route to domain-specific handler ─────────────────────────────────
        handler = _LOCATION_HANDLERS.get(domain, _set_location_standard)
        handler(driver, postcode)

        # ── Confirm popup is gone ─────────────────────────────────────────────
        try:
            WebDriverWait(driver, 4).until(
                EC.invisibility_of_element_located(
                    (By.ID, "nav-global-location-popover-link"
                     if False else "GLUXZipUpdateInput")))
        except TimeoutException:
            pass

        log_fn(f"  📍 Location set to **{postcode}** on `{domain}`")
        return True

    except (TimeoutException, WebDriverException) as exc:
        log_fn(
            f"  ⚠️ Could not set location on `{domain}` "
            f"({exc.__class__.__name__}) — scraping without location override")
        return False


def run_scrape(search_config, selected_domains, headless, delay,
               log_fn, progress_fn, postcodes=None, set_location=True):
    """
    postcodes: dict {domain: postcode_string} — overrides defaults.
    set_location: if True, sets the Deliver-to postcode before each domain's search.
    """
    options = Options()
    if headless:
        options.add_argument("--headless")
    options.set_preference(
        "general.useragent.override",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36",
    )
    driver      = webdriver.Firefox(options=options)
    driver.maximize_window()
    all_rows    = []
    terms       = list(search_config.keys())
    total_steps = len(terms) * len(selected_domains)
    step        = 0

    # Merge user overrides with defaults
    effective_postcodes = {**DOMAIN_DEFAULT_POSTCODE, **(postcodes or {})}

    try:
        for domain in selected_domains:

            # ── Set delivery location ONCE per domain ─────────────────────────
            if set_location:
                pc = effective_postcodes.get(domain, "")
                if pc:
                    set_delivery_location(driver, domain, pc, log_fn)

            log_fn(f"🌍 Scraping domain: **{domain}**")
            for term in terms:
                rules = search_config[term]
                log_fn(f"  🔍 Search term: **{term}**")

                url = f"https://{domain}/s?k={urllib.parse.quote_plus(term)}"
                try:
                    driver.get(url)

                    # Dismiss any "Continue shopping" or cookie overlay
                    # that may have appeared after navigation
                    _dismiss_interstitial(driver)

                    try:
                        WebDriverWait(driver, 8).until(
                            EC.presence_of_element_located(
                                (By.CSS_SELECTOR, "div.s-result-item")))
                    except TimeoutException:
                        log_fn(f"    ⚠️ Timeout / CAPTCHA on `{domain}` — skipping")
                        step += 1; progress_fn(step / total_steps); continue
                    time.sleep(random.uniform(delay[0], delay[1]))
                    rows = parse_html(driver.page_source, domain, term, rules)
                    all_rows.extend(rows)
                    log_fn(f"    ✅ {len(rows)} products found")
                except WebDriverException as e:
                    log_fn(f"    ❌ `{domain}` / `{term}` — {e}")
                step += 1; progress_fn(step / total_steps)
    finally:
        driver.quit()

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["price_usd"] = pd.to_numeric(df["price_usd"], errors="coerce").round(2)
    df = df.drop_duplicates(subset=["product_name", "origin_country", "price_usd"])
    col_order = ["product_type","search_term","origin_country","product_name",
                 "currency_code","currency","price","price_value","price_usd","rating","link"]
    df = df[[c for c in col_order if c in df.columns]]
    return df.reset_index(drop=True)

# ─────────────────────────────────────────────────────────────────────────────
# DATA CLEANING
# ─────────────────────────────────────────────────────────────────────────────

def apply_cleaning(df, opts):
    original_len = len(df)
    log = []

    if opts.get("remove_sponsored"):
        before = len(df)
        mask = df["product_name"].str.strip().str.lower().str.startswith("sponsored", na=True)
        df   = df[~mask]
        log.append(f"Removed **{before - len(df)}** sponsored listings")

    if opts.get("remove_no_price"):
        before = len(df)
        df     = df[df["price_usd"].notna() & (df["price_usd"] > 0)]
        log.append(f"Removed **{before - len(df)}** rows with missing/zero price")

    if opts.get("remove_no_rating"):
        before = len(df)
        df     = df[df["rating"].notna()]
        log.append(f"Removed **{before - len(df)}** rows with no rating")

    if opts.get("remove_outliers"):
        before = len(df)
        pct    = opts.get("outlier_pct", 99) / 100
        cap    = df["price_usd"].quantile(pct)
        df     = df[df["price_usd"] <= cap]
        log.append(f"Removed **{before - len(df)}** price outliers (above {opts['outlier_pct']}th pct = ${cap:.0f})")

    if opts.get("remove_duplicates"):
        before = len(df)
        df     = df.drop_duplicates(subset=["product_name", "origin_country", "price_usd"])
        log.append(f"Removed **{before - len(df)}** duplicate rows")

    log.append(f"**{len(df):,}** rows remain (from {original_len:,})")
    return df.reset_index(drop=True), log

# ─────────────────────────────────────────────────────────────────────────────
# EDA CHARTS
# ─────────────────────────────────────────────────────────────────────────────

def make_chart_avg_price_country(df):
    data = (df[df["price_usd"].notna()]
            .groupby("origin_country")["price_usd"]
            .agg(avg_price="mean", listings="count")
            .reset_index()
            .sort_values("avg_price", ascending=True))
    if data.empty:
        return None
    overall = data["avg_price"].mean()
    colors  = [PALETTE[0] if v >= overall else PALETTE[1] for v in data["avg_price"]]
    fig, ax = plt.subplots(figsize=(9, max(4, len(data) * 0.38)))
    bars = ax.barh(data["origin_country"], data["avg_price"], color=colors, edgecolor="white")
    for bar, n in zip(bars, data["listings"]):
        w = bar.get_width()
        ax.text(w + overall * 0.01, bar.get_y() + bar.get_height() / 2,
                f"${w:,.0f}  (n={n})", va="center", fontsize=8.5)
    ax.axvline(overall, color="grey", linestyle="--", lw=1.4, label=f"Overall avg ${overall:.0f}")
    from matplotlib.patches import Patch
    ax.legend(handles=[
        Patch(facecolor=PALETTE[0], label="Above avg"),
        Patch(facecolor=PALETTE[1], label="Below avg"),
        plt.Line2D([0],[0], color="grey", linestyle="--", lw=1.4, label=f"Avg ${overall:.0f}"),
    ], fontsize=9)
    ax.set_title("Average Price per Unit by Country (USD)", fontweight="bold", pad=10)
    ax.set_xlabel("Avg Price (USD)")
    ax.set_xlim(0, data["avg_price"].max() * 1.3)
    ax.spines[["top","right"]].set_visible(False)
    plt.tight_layout()
    return fig

def make_chart_price_distribution(df):
    data = df["price_usd"].dropna()
    if data.empty:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    ax = axes[0]
    ax.hist(data, bins=35, color=PALETTE[0], edgecolor="white", alpha=0.85)
    ax.axvline(data.mean(),   color="red",   linestyle="--", lw=1.6, label=f"Mean ${data.mean():.0f}")
    ax.axvline(data.median(), color="green", linestyle="--", lw=1.6, label=f"Median ${data.median():.0f}")
    ax.set_title("Price Distribution (USD)", fontweight="bold")
    ax.set_xlabel("Price (USD)"); ax.set_ylabel("Count")
    ax.legend(fontsize=9); ax.spines[["top","right"]].set_visible(False)

    ax2 = axes[1]
    if "product_type" in df.columns:
        order = (df[df["price_usd"].notna()]
                 .groupby("product_type")["price_usd"]
                 .median().sort_values(ascending=False).index)
        sns.boxplot(data=df[df["product_type"].isin(order)],
                    x="price_usd", y="product_type", order=order,
                    palette=PALETTE, ax=ax2, fliersize=2)
        ax2.set_title("Price by Product Type (USD)", fontweight="bold")
        ax2.set_xlabel("Price (USD)"); ax2.set_ylabel("")
        ax2.spines[["top","right"]].set_visible(False)

    plt.tight_layout()
    return fig

def make_chart_ratings(df):
    data = df["rating"].dropna()
    if data.empty:
        return None
    fig, axes = plt.subplots(1, 2, figsize=(13, 4.5))

    ax = axes[0]
    ax.hist(data, bins=20, color=PALETTE[1], edgecolor="white", alpha=0.85)
    ax.axvline(data.mean(),   color="red",   linestyle="--", lw=1.6, label=f"Mean {data.mean():.2f}")
    ax.axvline(data.median(), color="green", linestyle="--", lw=1.6, label=f"Median {data.median():.2f}")
    ax.set_title("Rating Distribution", fontweight="bold")
    ax.set_xlabel("Rating (out of 5)"); ax.set_ylabel("Count")
    ax.legend(fontsize=9); ax.spines[["top","right"]].set_visible(False)

    ax2 = axes[1]
    if "product_type" in df.columns:
        avg_r = (df.dropna(subset=["rating"])
                 .groupby("product_type")["rating"]
                 .mean().sort_values(ascending=True))
        bars  = ax2.barh(avg_r.index, avg_r.values, color=PALETTE[2])
        for bar in bars:
            w = bar.get_width()
            ax2.text(w + 0.02, bar.get_y() + bar.get_height() / 2,
                     f"{w:.2f}", va="center", fontsize=9)
        ax2.axvline(4.0, color="grey", linestyle=":", lw=1.2, label="4.0 line")
        ax2.set_xlim(0, 5.5)
        ax2.set_title("Avg Rating by Product Type", fontweight="bold")
        ax2.set_xlabel("Avg Rating"); ax2.legend(fontsize=9)
        ax2.spines[["top","right"]].set_visible(False)

    plt.tight_layout()
    return fig

def make_chart_listings_by_country(df):
    data = df["origin_country"].value_counts().head(15)
    if data.empty:
        return None
    fig, ax = plt.subplots(figsize=(9, max(4, len(data) * 0.38)))
    bars = ax.barh(data.index[::-1], data.values[::-1], color=PALETTE[0], edgecolor="white")
    for bar in bars:
        w = bar.get_width()
        ax.text(w + 0.3, bar.get_y() + bar.get_height() / 2,
                f"{w:,.0f}", va="center", fontsize=9)
    ax.set_title("Listings per Country (Top 15)", fontweight="bold", pad=10)
    ax.set_xlabel("Number of Listings")
    ax.set_xlim(0, data.max() * 1.15)
    ax.spines[["top","right"]].set_visible(False)
    plt.tight_layout()
    return fig

def make_chart_price_vs_rating(df):
    data = df.dropna(subset=["price_usd","rating"])
    if data.empty:
        return None
    fig, ax = plt.subplots(figsize=(9, 5))
    types   = data["product_type"].unique() if "product_type" in data.columns else ["All"]
    cmap    = {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(types)}
    if "product_type" in data.columns:
        for pt, grp in data.groupby("product_type"):
            ax.scatter(grp["price_usd"], grp["rating"], label=pt,
                       color=cmap[pt], alpha=0.5, s=35, edgecolors="white", lw=0.3)
    else:
        ax.scatter(data["price_usd"], data["rating"], color=PALETTE[0], alpha=0.5, s=35)
    z  = np.polyfit(data["price_usd"], data["rating"], 1)
    xs = np.linspace(data["price_usd"].min(), data["price_usd"].max(), 200)
    ax.plot(xs, np.poly1d(z)(xs), "k--", lw=1.4, alpha=0.6, label="Trend")
    ax.set_title("Price vs. Rating", fontweight="bold", pad=10)
    ax.set_xlabel("Price (USD)"); ax.set_ylabel("Rating")
    ax.legend(fontsize=9, loc="lower right")
    ax.spines[["top","right"]].set_visible(False)
    plt.tight_layout()
    return fig

def make_chart_product_type_dist(df):
    if "product_type" not in df.columns:
        return None
    data = df["product_type"].value_counts()
    fig, ax = plt.subplots(figsize=(9, max(3, len(data) * 0.4)))
    bars = ax.barh(data.index[::-1], data.values[::-1],
                   color=PALETTE[:len(data)][::-1], edgecolor="white")
    for bar in bars:
        w = bar.get_width()
        ax.text(w + 0.5, bar.get_y() + bar.get_height() / 2,
                f"{w:,.0f}", va="center", fontsize=9)
    ax.set_title("Listings by Product Type", fontweight="bold", pad=10)
    ax.set_xlabel("Count")
    ax.set_xlim(0, data.max() * 1.15)
    ax.spines[["top","right"]].set_visible(False)
    plt.tight_layout()
    return fig

# ─────────────────────────────────────────────────────────────────────────────
# STREAMLIT APP
# ─────────────────────────────────────────────────────────────────────────────

st.set_page_config(page_title="Amazon Scraper", page_icon="🛒", layout="wide")
plt.style.use("seaborn-v0_8-whitegrid")
plt.rcParams.update({"figure.dpi": 130, "font.size": 10,
                     "axes.titlesize": 12, "axes.titleweight": "bold"})

# ── Session state ────────────────────────────────────────────────────────────
for key, default in [
    ("rules",       []),
    ("results_df",  None),
    ("cleaned_df",  None),
    ("log_lines",   []),
]:
    if key not in st.session_state:
        st.session_state[key] = default

# ════════════════════════════════════════════════════════════════════════════
# SIDEBAR
# ════════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.header("⚙️ Scraper Settings")
    headless = st.toggle("Headless browser (no window)", value=True)
    delay_min, delay_max = st.slider(
        "Delay between requests (s)", 0.5, 10.0, (1.5, 3.5), step=0.5)

    st.subheader("🌍 Marketplaces")
    all_labels      = list(AMAZON_DOMAINS.values())
    selected_labels = st.multiselect("Countries to scrape",
                                     options=all_labels, default=all_labels)
    label_to_domain  = {v: k for k, v in AMAZON_DOMAINS.items()}
    selected_domains = [label_to_domain[l] for l in selected_labels]

    st.divider()

    # ── Location / Postcode Settings ──────────────────────────────────────
    st.header("📍 Delivery Location")
    st.caption("Set the postcode used for the 'Deliver to' widget on each marketplace, "
               "so results are local to that country.")

    set_location = st.toggle("Set delivery location before scraping", value=True)

    if set_location:
        st.caption("Edit any postcode below. Leave blank to skip location-setting for that domain.")
        postcode_overrides = {}
        with st.expander("📮 Postcodes per marketplace", expanded=False):
            for domain, default_pc in DOMAIN_DEFAULT_POSTCODE.items():
                country = AMAZON_DOMAINS.get(domain, domain)
                val = st.text_input(
                    f"{country} ({domain})",
                    value=default_pc,
                    key=f"pc_{domain}",
                    label_visibility="visible",
                )
                postcode_overrides[domain] = val.strip()
    else:
        postcode_overrides = {}

    st.divider()

    # ── Data Cleaning Options ─────────────────────────────────────────────
    st.header("🧹 Data Cleaning Options")
    st.caption("Applied after scraping when you click **Apply Cleaning**.")
    clean_sponsored  = st.checkbox("Remove sponsored listings",  value=True)
    clean_no_price   = st.checkbox("Remove rows with no price",  value=True)
    clean_no_rating  = st.checkbox("Remove rows with no rating", value=False)
    clean_duplicates = st.checkbox("Remove duplicates",          value=True)
    clean_outliers   = st.checkbox("Remove price outliers",      value=True)
    outlier_pct      = st.slider("Outlier threshold (percentile)",
                                  80, 99, 99, step=1,
                                  disabled=not clean_outliers)

# ════════════════════════════════════════════════════════════════════════════
# MAIN — TABS
# ════════════════════════════════════════════════════════════════════════════
st.title("🛒 Amazon Product Scraper")
tab_rules, tab_scrape, tab_clean, tab_eda = st.tabs(
    ["📋 Rules", "🚀 Scrape", "🧹 Clean & Export", "📊 Visualise"])


# ══════════════════════════════════════════════
# TAB 1 — RULES  (editable table)
# ══════════════════════════════════════════════
with tab_rules:
    st.subheader("Search Rules")
    st.caption(
        "Add rows directly in the table below **or upload a CSV / Excel file**. "
        "Fill in **Search Term** and **Product Type** (required). "
        "Keywords are comma-separated — e.g. `4k, mirrorless, dslr`. "
        "Click **Save Rules** when done."
    )

    # ── File Upload ────────────────────────────────────────────────────────
    with st.expander("📂 Import rules from CSV or Excel file", expanded=not st.session_state.rules):
        st.markdown(
            "Upload a **CSV** or **Excel (.xlsx)** file. "
            "Expected columns *(names are flexible — see mapping below)*:\n\n"
            "| Column | Accepted names |\n"
            "|--------|----------------|\n"
            "| Search Term | `search_term`, `search term`, `keyword`, `query` |\n"
            "| Product Type | `target_product_type`, `type`, `product_type`, `label` |\n"
            "| Include Keywords | `include_keywords`, `include`, `include keywords` |\n"
            "| Exclude Keywords | `exclude_keywords`, `exclude`, `exclude keywords` |\n\n"
            "Keywords can be separated by commas **or** pipes (`|`)."
        )

        uploaded_file = st.file_uploader(
            "Choose a file",
            type=["csv", "xlsx", "xls"],
            key="rules_file_uploader",
            label_visibility="collapsed",
        )

        if uploaded_file is not None:
            try:
                fname = uploaded_file.name.lower()
                if fname.endswith(".csv"):
                    raw = uploaded_file.read()
                    text = raw.decode("utf-8", errors="replace")
                    header_line = text.split("\n")[0]
                    # Count delimiters in header only — most reliable way to detect sep
                    counts = {d: header_line.count(d) for d in [";", "\t", ","]}
                    sep = max(counts, key=counts.get)
                    up_df = pd.read_csv(
                        io.BytesIO(raw),
                        sep=sep,
                        engine="python",
                        on_bad_lines="skip",
                    )
                else:
                    up_df = pd.read_excel(uploaded_file)

                # Normalise column names: strip whitespace, lowercase, spaces→underscores
                up_df.columns = [
                    re.sub(r"\s+", "_", c.strip().lower()) for c in up_df.columns
                ]

                COL_MAP = {
                    "search_term": [
                        "search_term", "search_terms", "searchterm",
                        "keyword", "keywords", "query", "search",
                    ],
                    "type": [
                        "target_product_type", "product_type", "type",
                        "label", "category", "product_label",
                    ],
                    "include": [
                        "include_keywords", "include_keyword",
                        "include_kw", "include", "includes",
                    ],
                    "exclude": [
                        "exclude_keywords", "exclude_keyword",
                        "exclude_kw", "exclude", "excludes", "exclude_key",
                    ],
                }

                def _find_col(df, candidates):
                    for c in candidates:
                        norm = re.sub(r"\s+", "_", c.strip().lower())
                        if norm in df.columns:
                            return norm
                    return None

                mapped = {}
                missing = []
                for target, candidates in COL_MAP.items():
                    found = _find_col(up_df, candidates)
                    if found:
                        mapped[target] = found
                    elif target in ("search_term", "type"):
                        missing.append(target)

                if missing:
                    st.error(
                        f"❌ Could not find required column(s): **{', '.join(missing)}**. "
                        f"Columns detected in your file: `{list(up_df.columns)}`. "
                        "Please check your file headers match the expected names above."
                    )
                else:
                    # Build preview dataframe
                    preview_rows = []
                    for _, row in up_df.iterrows():
                        term  = str(row.get(mapped["search_term"], "")).strip().lower()
                        ptype = str(row.get(mapped["type"], "")).strip()
                        if not term or not ptype or term == "nan" or ptype == "nan":
                            continue
                        inc_raw = str(row.get(mapped.get("include", ""), "")) if "include" in mapped else ""
                        exc_raw = str(row.get(mapped.get("exclude", ""), "")) if "exclude" in mapped else ""
                        # Accept both comma and pipe separators
                        def _split_kw(s):
                            s = s.replace("|", ",") if "|" in s else s
                            return [k.strip().lower() for k in s.split(",") if k.strip() and k.strip() != "nan"]
                        preview_rows.append({
                            "search_term": term,
                            "type":        ptype,
                            "include":     ", ".join(_split_kw(inc_raw)),
                            "exclude":     ", ".join(_split_kw(exc_raw)),
                        })

                    if preview_rows:
                        st.success(f"✅ Found **{len(preview_rows)} rule(s)** in the file. Preview:")
                        st.dataframe(pd.DataFrame(preview_rows), use_container_width=True)
                        if st.button("⬆️ Load these rules into the table", type="primary", key="load_uploaded_rules"):
                            st.session_state.rules = [
                                {
                                    "search_term": r["search_term"],
                                    "type":        r["type"],
                                    "include":     parse_kw(r["include"]),
                                    "exclude":     parse_kw(r["exclude"]),
                                }
                                for r in preview_rows
                            ]
                            st.success(f"✅ {len(preview_rows)} rule(s) loaded! You can now edit them in the table below.")
                            st.rerun()
                    else:
                        st.warning("⚠️ No valid rows found in the file. Make sure Search Term and Product Type columns are not empty.")

            except Exception as e:
                st.error(f"❌ Failed to read file: {e}")

    st.divider()

    # Build display dataframe — seed with empty row if no rules yet
    if st.session_state.rules:
        rules_df = pd.DataFrame(st.session_state.rules)
        rules_df["include"] = rules_df["include"].apply(
            lambda x: ", ".join(x) if isinstance(x, list) else x)
        rules_df["exclude"] = rules_df["exclude"].apply(
            lambda x: ", ".join(x) if isinstance(x, list) else x)
    else:
        rules_df = pd.DataFrame([{
            "search_term": "",
            "type":        "",
            "include":     "",
            "exclude":     "",
        }])

    edited_df = st.data_editor(
        rules_df,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "search_term": st.column_config.TextColumn(
                "Search Term ✱",
                help="The keyword to search on Amazon (e.g. 'digital camera')",
            ),
            "type": st.column_config.TextColumn(
                "Product Type ✱",
                help="Label assigned to matching products (e.g. 'Digital Camera')",
            ),
            "include": st.column_config.TextColumn(
                "Include Keywords",
                help="Product must contain at least one of these words (comma-separated). e.g. 4k, mirrorless, dslr",
            ),
            "exclude": st.column_config.TextColumn(
                "Exclude Keywords",
                help="Skip product if it contains any of these words (comma-separated). e.g. case, battery, strap",
            ),
        },
        key="rules_editor",
    )

    col_save, col_clear = st.columns([1, 1])
    with col_save:
        if st.button("💾 Save Rules", width="stretch", type="primary"):
            new_rules = []
            for _, row in edited_df.iterrows():
                term  = str(row.get("search_term", "")).strip().lower()
                ptype = str(row.get("type", "")).strip()
                if not term or not ptype:
                    continue
                new_rules.append({
                    "search_term": term,
                    "type":        ptype,
                    "include":     parse_kw(str(row.get("include", ""))),
                    "exclude":     parse_kw(str(row.get("exclude", ""))),
                })
            st.session_state.rules = new_rules
            if new_rules:
                st.success(f"✅ Saved {len(new_rules)} rule(s).")
            else:
                st.warning("No valid rules found — make sure Search Term and Product Type are filled in.")
            st.rerun()

    with col_clear:
        if st.button("🗑️ Clear All Rules", width="stretch"):
            st.session_state.rules = []
            st.rerun()


# ══════════════════════════════════════════════
# TAB 2 — SCRAPE
# ══════════════════════════════════════════════
with tab_scrape:
    st.subheader("Run Scraper")

    rules_ok   = len(st.session_state.rules) > 0
    domains_ok = len(selected_domains) > 0

    if not rules_ok:
        st.warning("Add at least one rule in the **Rules** tab first.")
    if not domains_ok:
        st.warning("Select at least one marketplace in the sidebar.")

    run_btn = st.button(
        "🚀 Run Scraper", type="primary",
        width="stretch",
        disabled=(not rules_ok or not domains_ok),
    )

    if run_btn:
        search_config = {}
        for r in st.session_state.rules:
            t = r["search_term"]
            if t not in search_config:
                search_config[t] = []
            search_config[t].append({
                "type":    r["type"],
                "include": r["include"],
                "exclude": r["exclude"],
            })

        st.session_state.log_lines = []
        log_area     = st.empty()
        progress_bar = st.progress(0, text="Starting…")
        log_lines    = []

        def log_fn(msg):
            log_lines.append(msg)
            log_area.markdown("\n\n".join(log_lines[-30:]))  # last 30 lines

        def progress_fn(val):
            progress_bar.progress(val, text=f"{int(val*100)}% complete")

        with st.spinner("Scraping in progress…"):
            df = run_scrape(
                search_config    = search_config,
                selected_domains = selected_domains,
                headless         = headless,
                delay            = (delay_min, delay_max),
                log_fn           = log_fn,
                progress_fn      = progress_fn,
                postcodes        = postcode_overrides,
                set_location     = set_location,
            )

        progress_bar.progress(1.0, text="Done!")
        st.session_state.results_df = df
        st.session_state.cleaned_df = None   # reset cleaned when new scrape
        st.session_state.log_lines  = log_lines

        if df.empty:
            st.warning("No results collected. Check settings or try again.")
        else:
            st.success(f"✅ Done — **{len(df):,}** products collected.")
            st.dataframe(df.head(50), width="stretch", hide_index=True)
            st.caption(f"Showing first 50 of {len(df):,} rows.")


# ══════════════════════════════════════════════
# TAB 3 — CLEAN & EXPORT
# ══════════════════════════════════════════════
with tab_clean:
    raw = st.session_state.results_df

    if raw is None or raw.empty:
        st.info("Run the scraper first to get data here.")
    else:
        st.subheader("🧹 Data Cleaning")
        st.write(f"Raw dataset: **{len(raw):,} rows**")

        if st.button("▶️ Apply Cleaning", width="stretch", type="primary"):
            opts = {
                "remove_sponsored":  clean_sponsored,
                "remove_no_price":   clean_no_price,
                "remove_no_rating":  clean_no_rating,
                "remove_duplicates": clean_duplicates,
                "remove_outliers":   clean_outliers,
                "outlier_pct":       outlier_pct,
            }
            cleaned, log = apply_cleaning(raw.copy(), opts)
            st.session_state.cleaned_df = cleaned
            for line in log:
                st.markdown(f"- {line}")

        display_df = st.session_state.cleaned_df if st.session_state.cleaned_df is not None else raw
        label      = "cleaned" if st.session_state.cleaned_df is not None else "raw"
        st.subheader(f"Preview ({label}, {len(display_df):,} rows)")

        # ── Filters ──────────────────────────────────────────────────────────
        with st.expander("🔎 Filter results"):
            fc1, fc2, fc3 = st.columns(3)
            with fc1:
                f_term    = st.multiselect("Search term",
                    sorted(display_df["search_term"].dropna().unique()), key="f_term")
            with fc2:
                f_country = st.multiselect("Country",
                    sorted(display_df["origin_country"].dropna().unique()), key="f_country")
            with fc3:
                f_type    = st.multiselect("Product type",
                    sorted(display_df["product_type"].dropna().unique()), key="f_type")

            p_min = float(display_df["price_usd"].min(skipna=True) or 0)
            p_max = float(display_df["price_usd"].max(skipna=True) or 9999)
            price_range = st.slider("Price range (USD)", p_min, p_max,
                                    (p_min, p_max), step=1.0, key="f_price")

        filtered = display_df.copy()
        if f_term:    filtered = filtered[filtered["search_term"].isin(f_term)]
        if f_country: filtered = filtered[filtered["origin_country"].isin(f_country)]
        if f_type:    filtered = filtered[filtered["product_type"].isin(f_type)]
        filtered = filtered[
            filtered["price_usd"].isna() |
            ((filtered["price_usd"] >= price_range[0]) &
             (filtered["price_usd"] <= price_range[1]))]

        st.dataframe(filtered, width="stretch", hide_index=True)

        # ── Download ──────────────────────────────────────────────────────────
        st.subheader("💾 Download")
        dl1, dl2 = st.columns(2)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        with dl1:
            st.download_button("⬇️ CSV", filtered.to_csv(index=False).encode(),
                               f"results_{ts}.csv", "text/csv",
                               width="stretch")
        with dl2:
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="xlsxwriter") as w:
                filtered.to_excel(w, index=False, sheet_name="Results")
            st.download_button(
                "⬇️ Excel", buf.getvalue(), f"results_{ts}.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                width="stretch")


# ══════════════════════════════════════════════
# TAB 4 — EDA VISUALISATIONS
# ══════════════════════════════════════════════
with tab_eda:
    # Use cleaned data if available, otherwise raw
    eda_df = (st.session_state.cleaned_df
              if st.session_state.cleaned_df is not None
              else st.session_state.results_df)

    if eda_df is None or eda_df.empty:
        st.info("Run the scraper (and optionally clean the data) to see visualisations here.")
    else:
        note = "cleaned" if st.session_state.cleaned_df is not None else "raw"
        st.caption(f"Using **{note}** data — {len(eda_df):,} rows.")

        # ── Chart selection ───────────────────────────────────────────────────
        chart_options = {
            "Avg Price by Country":     make_chart_avg_price_country,
            "Price Distribution":       make_chart_price_distribution,
            "Rating Distribution":      make_chart_ratings,
            "Listings per Country":     make_chart_listings_by_country,
            "Price vs. Rating":         make_chart_price_vs_rating,
            "Listings by Product Type": make_chart_product_type_dist,
        }

        selected_charts = st.multiselect(
            "Select charts to display",
            options=list(chart_options.keys()),
            default=list(chart_options.keys()),
        )

        for chart_name in selected_charts:
            st.subheader(chart_name)
            fig = chart_options[chart_name](eda_df)
            if fig:
                st.pyplot(fig, width="stretch")
                buf = io.BytesIO()
                fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
                st.download_button(
                    f"⬇️ Download '{chart_name}'",
                    buf.getvalue(),
                    file_name=f"{sanitize_for_path(chart_name)}.png",
                    mime="image/png",
                    key=f"dl_{chart_name}",
                )
                plt.close(fig)
            else:
                st.warning(f"Not enough data to render '{chart_name}'.")
            st.divider()
