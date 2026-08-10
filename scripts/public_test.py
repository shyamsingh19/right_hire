from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import pandas as pd
import requests

# You can change this path to either an Excel file (.xlsx) or a CSV file (.csv)
EXCEL_FILE_PATH = "storage/Embedded Hardware Engineer full.csv"
# EXCEL_FILE_PATH = "/home/shyam/Downloads/Associate-Human Resources And Administration (Responses).xlsx"

MAX_WORKERS = 10  # Number of concurrent threads


def check_gdrive_link(url):
  if not url or pd.isna(url):
    return "No Link Provided"

  url = str(url).strip()
  try:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        )
    }
    response = requests.get(url, headers=headers, allow_redirects=True, timeout=8)

    if response.status_code == 200:
      content_lower = response.text.lower()
      if (
          "request access" in content_lower
          or "you need access" in content_lower
          or "sign in" in content_lower
      ):
        return "Private (Permission Required)"
      else:
        return "Public / Accessible"
    elif response.status_code == 404:
      return "Broken Link (404 Not Found)"
    else:
      return f"Status Code: {response.status_code}"
  except requests.RequestException as e:
    return f"Error: {e}"


def process_row(index, row):
  name = str(row.get("Your Name", "")).strip()
  email = str(row.get("Email address", "")).strip()
  link = row.get("Attach Your CV", "")

  status = check_gdrive_link(link)
  return index, name, email, status


def main():
  try:
    print(f"Reading file from: {EXCEL_FILE_PATH}")
    
    # Automatically detect file type and read accordingly
    ext = os.path.splitext(EXCEL_FILE_PATH)[1].lower()
    if ext == ".csv":
      df = pd.read_csv(EXCEL_FILE_PATH)
    elif ext in [".xls", ".xlsx"]:
      df = pd.read_excel(EXCEL_FILE_PATH)
    else:
      print(f"Error: Unsupported file extension '{ext}'. Use .csv or .xlsx")
      return

    total_rows = len(df)

    print(
        f"Found {total_rows} rows. Checking links concurrently with live"
        " updates...\n"
    )
    print(f"{'Sr. No.':<8} | {'Name':<25} | {'Email':<30} | {'Link Status'}")
    print("-" * 100)

    rows = list(df.iterrows())
    public_count = 0

    # Use ThreadPoolExecutor to check concurrently and print live as they finish
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
      futures = {
          executor.submit(process_row, idx + 1, row): idx
          for idx, (_, row) in enumerate(rows)
      }

      for future in as_completed(futures):
        idx, name, email, status = future.result()

        if "Public" in status:
          public_count += 1
          status_display = f"\033[92m{status}\033[0m"  # Green
        else:
          status_display = f"\033[91m{status}\033[0m"  # Red

        print(f"{idx:<8} | {name:<25} | {email:<30} | {status_display}")

    print("-" * 100)
    print(
        f"Done! Found {public_count} public/accessible resume links out of"
        f" {total_rows} total rows."
    )

  except FileNotFoundError:
    print(f"Error: Could not find the file at '{EXCEL_FILE_PATH}'.")
  except Exception as e:
    print(f"An unexpected error occurred: {e}")


if __name__ == "__main__":
  main()