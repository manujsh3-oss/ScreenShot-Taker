from playwright.sync_api import sync_playwright
from pathlib import Path
from datetime import datetime, timezone, timedelta
import time
import re
import pandas as pd
import io
import json
import os
import requests
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

SCOPES = ["https://www.googleapis.com/auth/drive"]

def get_drive_service():
    creds = None

    token_data = os.environ.get("GDRIVE_TOKEN_JSON")
    if token_data:
        creds = Credentials.from_authorized_user_info(json.loads(token_data), SCOPES)
    elif os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            creds_data = os.environ.get("GDRIVE_CREDENTIALS_JSON")
            if creds_data:
                import tempfile
                with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
                    f.write(creds_data)
                    temp_path = f.name
                flow = InstalledAppFlow.from_client_secrets_file(temp_path, SCOPES)
            else:
                flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as token:
            token.write(creds.to_json())

    return build("drive", "v3", credentials=creds)

url = os.environ["GOOGLE_SHEET_URL"].strip()
GDRIVE_FOLDER_ID = os.environ["GDRIVE_FOLDER_ID"]

response = requests.get(url)
response.raise_for_status()
df = pd.read_csv(io.StringIO(response.text))

def handle_amazon_continue_shopping(page):

    possible_selectors = [
        'input[type="submit"]',
        'button',
        'a'
    ]

    texts = [
        "Continue shopping",
        "Continue",
        "Proceed"
    ]

    for selector in possible_selectors:

        try:
            elements = page.locator(selector)

            count = elements.count()

            for i in range(count):

                element = elements.nth(i)

                try:
                    text = element.inner_text(timeout=2000).strip()

                except:
                    text = element.get_attribute("value") or ""

                for target in texts:

                    if target.lower() in text.lower():

                        print(f"Clicking button: {text}")

                        element.click()

                        page.wait_for_timeout(5000)

                        return True

        except Exception as e:
            print(f"Button handling error: {e}")

    return False


def normalize_url(url):

    url = str(url).strip()

    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    return url


def sanitize_filename(text):
    return re.sub(r"[^\w\-]", "_", str(text))

IST = timezone(timedelta(hours=5, minutes=30))
def timestamp():
    return datetime.now(IST).strftime("%Y-%m-%d_%H-%M-%S")




def get_or_create_subfolder(service, folder_name, parent_id):
    """Returns the Drive folder ID, creating it if it doesn't exist."""
    query = (
        f"name='{folder_name}' and "
        f"'{parent_id}' in parents and "
        f"mimeType='application/vnd.google-apps.folder' and "
        f"trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]
    
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id]
    }
    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]

def upload_screenshot_to_drive(service, screenshot_bytes, filename, subfolder_id):
    """Uploads a PNG screenshot (bytes) to the given Drive folder."""
    media = MediaIoBaseUpload(
        io.BytesIO(screenshot_bytes),
        mimetype="image/png",
        resumable=False
    )
    metadata = {"name": filename, "parents": [subfolder_id]}
    service.files().create(body=metadata, media_body=media, fields="id").execute()
    print(f"Uploaded to Drive: {filename}")

drive_service = get_drive_service()



with sync_playwright() as p:

    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled"
        ]
    )

    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        viewport={
            "width": 1440,
            "height": 900
        },
        locale="en-US"
    )

    page = context.new_page()

    print("Columns found:", df.columns.tolist())

    for index, row in df.iterrows():
        print(f"index in df : {index}")
        print(f"row in df : {row}")

        brand = row["Brand"]
        asin_name = row["ASIN Name"]
        model = row["Model"]
        asin = row["ASIN"]


        az_url = normalize_url(row["Az Website Link"])
        ic_url = normalize_url(row["IC Website Link"])

        date_folder = datetime.now(IST).strftime("%d %B %Y")
        brand_folder = sanitize_filename(brand)
        asin_folder = sanitize_filename(asin)
        
        date_id = get_or_create_subfolder(drive_service, date_folder, GDRIVE_FOLDER_ID)
        brand_id = get_or_create_subfolder(drive_service, brand_folder, date_id)
        subfolder_id = get_or_create_subfolder(drive_service, asin_folder, brand_id)


        print("\n===================================")
        print(f"Processing ASIN: {asin}")
        print("===================================\n")


        websites = [
            ("amazon", az_url),
            ("ic", ic_url)
        ]

        for site_name, url in websites:

            success = False


            for attempt in range(1, 4):

                try:

                    print(f"\nAttempt {attempt}: {url}")

                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=60000
                    )


                    page.wait_for_timeout(5000)


                    if "amazon." in url or "amzn." in url:

                        handle_amazon_continue_shopping(page)

                        page.wait_for_timeout(5000)

                    page.wait_for_timeout(3000)



                    capture_time = timestamp()
                    file_name = f"{site_name}_{capture_time}.png"
                    screenshot_bytes = page.screenshot(full_page=True)
                    upload_screenshot_to_drive(drive_service, screenshot_bytes, file_name, subfolder_id)


                    success = True

                    break

                except Exception as e:

                    print(f"Error: {e}")

                    if attempt == 3:
                        print(f"FAILED: {url}")


            time.sleep(2)

    browser.close()

print("\nAll screenshots completed.")
