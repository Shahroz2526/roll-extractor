import glob
import os
import re
import cv2
import easyocr
import numpy as np
import pandas as pd

# EasyOCR Init (GPU = False for standard CPU)
reader = easyocr.Reader(["en"], gpu=False)


def process_scanned_folder(base_folder, excel_path, output_excel_path):
    print(f"\n🚀 Excel Loading: {excel_path}")
    try:
        df = pd.read_excel(excel_path)
    except Exception as e:
        print(f"❌ Excel File Read Error: {e}")
        return

    # Column Detection
    roll_col = next((c for c in df.columns if "ROLL" in str(c).upper()), None)
    script_col = next(
        (
            c
            for c in df.columns
            if any(k in str(c).upper() for k in ["SCRIPT", "SCRIPT#", "SCRIPT NO"])
        ),
        "Script No",
    )
    page_col = next(
        (c for c in df.columns if any(k in str(c).upper() for k in ["PG NO", "PAGE"])),
        "PG NO.",
    )

    if script_col not in df.columns:
        df[script_col] = ""
    df[script_col] = df[script_col].astype(str)

    # Sub-folders samait saari JPEGs search karne ke liye recursive globbing
    image_files = []
    for ext in ("**/*.jpg", "**/*.jpeg", "**/*.png"):
        image_files.extend(glob.glob(os.path.join(base_folder, ext), recursive=True))

    print(f"📸 Total Scanned Images Found (in all sub-folders): {len(image_files)}\n")

    if len(image_files) == 0:
        print(
            f"❌ '{base_folder}' folder mein koi image file nahi mili! Path check"
            " karein."
        )
        return

    page_script_map = {}

    # Read each scanned image
    for idx, img_path in enumerate(image_files, start=1):
        file_name = os.path.basename(img_path)

        # Extract Page Number from image file name (e.g., "106.jpg" -> Page 106)
        page_match = re.search(r"\d+", os.path.splitext(file_name)[0])
        page_num = page_match.group(0) if page_match else str(idx)

        print(f"[{idx}/{len(image_files)}] Reading Page {page_num} ({file_name})...")

        try:
            # Read image using OpenCV
            img = cv2.imread(img_path)

            if img is None:
                print(f"   ⚠️ Image load nahi ho saki: {file_name}")
                continue

            # EasyOCR execution
            ocr_results = reader.readtext(img)

            extracted_scripts = []
            for bbox, text, prob in ocr_results:
                clean_digit_text = re.sub(r"\D", "", text)  # Sirf digits
                # Filter 6 to 8 digit Script Numbers
                if (
                    len(clean_digit_text) >= 6
                    and len(clean_digit_text) <= 8
                    and prob > 0.35
                ):
                    extracted_scripts.append(clean_digit_text)

            if extracted_scripts:
                page_script_map[str(page_num)] = extracted_scripts
                print(f"   -> Found Script Numbers: {extracted_scripts}")
            else:
                print("   -> No clear script number detected.")

        except Exception as e:
            print(f"   ❌ Error reading {file_name}: {e}")

    # Map extracted script numbers back to Excel
    print("\n📊 Mapping Extracted Script Numbers into Excel...")
    updated_count = 0

    for index_row, row in df.iterrows():
        raw_pg = str(row[page_col]).strip().split(".")[0]

        if raw_pg in page_script_map and page_script_map[raw_pg]:
            assigned_script = page_script_map[raw_pg].pop(0)
            df.at[index_row, script_col] = str(assigned_script)
            updated_count += 1

    # Save final updated Excel
    df.to_excel(output_excel_path, index=False, engine="openpyxl")
    print(f"\n✅ Processing Done! Updated {updated_count} rows.")
    print(f"💾 Saved Output To: {output_excel_path}")


if __name__ == "__main__":
    # Paths match your folder setup:
    BASE_FOLDER_PATH = r"Attendance Annual I 2026"
    EXCEL_INPUT = r"processed\Processed_Excel_Sample_2.xlsx"
    EXCEL_OUTPUT = r"Final_Script_Updated_Excel.xlsx"

    process_scanned_folder(BASE_FOLDER_PATH, EXCEL_INPUT, EXCEL_OUTPUT)
