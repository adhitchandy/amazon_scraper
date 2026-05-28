# 🛒 Amazon Product Scraper (Streamlit App)

A multi-country Amazon scraper with built-in data cleaning and visualization, powered by Streamlit.

---

## 🚀 Features

- Scrape multiple Amazon marketplaces (US, DE, UK, JP, etc.)
- Automatic currency detection and conversion to USD
- Delivery-location simulation via postcode
- Rule-based product classification
- Data cleaning (duplicates, missing values, outliers)
- Built-in visualizations (price, ratings, distribution)

---

## 🧩 Requirements

- Python 3.9+
- Firefox browser
- Geckodriver (for Selenium)

---

## ⚙️ Installation

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/amazon-scraper-app.git
cd amazon-scraper-app
```

### 2. Create a virtual environment (recommended)

```bash
python -m venv venv

# Activate on Windows
venv\Scripts\activate

# Activate on Mac/Linux
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

---

## 🌐 Selenium Setup (IMPORTANT)

### Install Firefox

Download and install Firefox:
https://www.mozilla.org/firefox/

### Install Geckodriver

Download from:
https://github.com/mozilla/geckodriver/releases

Steps:
1. Download the version matching your OS
2. Extract the file
3. Add the folder to your system PATH

---

## ▶️ Run the App

```bash
streamlit run app.py
```

The app will open in your browser automatically.

---

## 📊 How to Use

1. Define scraping rules (search terms, product types, keywords)
2. Select marketplaces
3. Optionally set delivery postcodes
4. Run scraping
5. Clean data
6. Explore visualizations
7. Export results

---

## ⚠️ Important Notes

- Amazon may block scraping via CAPTCHA or rate limiting
- Results may vary depending on region and timing
- Use delays and avoid aggressive scraping
- This project is intended for educational and research purposes only

---

## 📁 Project Structure

```
amazon-scraper-app/
│
├── app.py
├── requirements.txt
├── README.md
└── .gitignore
```

---

## 🌍 Deployment (Optional)

### Streamlit Cloud (Recommended)

1. Push this repo to GitHub
2. Go to https://streamlit.io/cloud
3. Connect your repo
4. Deploy `app.py`

---

## 👨‍💻 Author

Your Name

---

## 📄 License

Add your preferred license here (e.g., MIT License)
