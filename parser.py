import pdfplumber
import pytesseract
from pdf2image import convert_from_path
import re
import os

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def clean_venue_string(venue):
    if not venue or venue == "N/A":
        return "N/A"
    # Remove START TIME, END TIME, and any time patterns like 09:30 or 12:30
    cleaned = re.sub(r"START\s*TIME:?.*", "", venue, flags=re.IGNORECASE)
    cleaned = re.sub(r"END\s*TIME:?.*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b\d{1,2}:\d{2}\b", "", cleaned)
    return cleaned.replace("|", "").strip()


def clean_college_string(college):
    if not college or college == "N/A":
        return "N/A"
    # Remove Roman Class Numerals (XI, XII, XI., XII.) from the end of the college name
    cleaned = re.sub(r"\b(XI|XII)\b\.?$", "", college, flags=re.IGNORECASE).strip()
    return cleaned.replace("|", "").strip()


def parse_single_pdf(pdf_path):
    roll_data = {}

    with pdfplumber.open(pdf_path) as pdf:
        print(f"\nTotal Pages : {len(pdf.pages)}\n")

        for page_number, page in enumerate(pdf.pages, start=1):
            text = page.extract_text()
            if not text:
                continue

            words = page.extract_words()

            # -----------------------------------------------------------
            # 1. EXACT VENUE NAME
            # -----------------------------------------------------------
            page_venue = "N/A"
            venue_y = None

            for w in words:
                if "VENUE" in w["text"].upper():
                    venue_y = w["top"]
                    break

            if venue_y is not None:
                same_line_words = [
                    w["text"]
                    for w in words
                    if abs(w["top"] - venue_y) < 12
                    and "VENUE" not in w["text"].upper()
                    and "NAME:" not in w["text"].upper()
                ]
                if same_line_words:
                    page_venue = " ".join(same_line_words).strip()

            if page_venue == "N/A" or not page_venue:
                lines = [l.strip() for l in text.split("\n") if l.strip()]
                for i, line in enumerate(lines):
                    if "VENUE NAME:" in line:
                        if i + 1 < len(lines):
                            page_venue = lines[i + 1].strip()
                        break

            # -----------------------------------------------------------
            # 2. EXACT COLLEGE NAME
            # -----------------------------------------------------------
            page_college = "N/A"
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            for line in lines:
                if any(
                    k in line
                    for k in [
                        "School",
                        "College",
                        "Grammar",
                        "Secondary",
                        "Higher",
                        "Academy",
                        "System",
                    ]
                ):
                    if (
                        not any(
                            k in line
                            for k in [
                                "ZIAUDDIN",
                                "EXAMINATION",
                                "BOARD",
                                "ATTENDANCE SHEET",
                            ]
                        )
                        and line != page_venue
                    ):
                        clean_c = (
                            line.split("START TIME")[0]
                            .split("LVL")[0]
                            .split("09:30")[0]
                            .strip()
                        )
                        if len(clean_c) > 3:
                            page_college = clean_c
                            break

            # Applying Cleanups
            page_venue = clean_venue_string(page_venue)
            page_college = clean_college_string(page_college)

            # -----------------------------------------------------------
            # 3. ROLL NUMBER & STUDENT MATCHING
            # -----------------------------------------------------------
            student_rows = False
            for line in lines:
                if "ROLL#" in line or "STUDENT NAME" in line:
                    student_rows = True
                    continue

                if not student_rows:
                    continue

                match = re.search(r"\b\d{6}\b", line)
                if not match:
                    continue

                roll = match.group()
                parts = [
                    p.replace("|", "").strip()
                    for p in line.split()
                    if p.replace("|", "").strip()
                ]

                if roll in parts:
                    roll_index = parts.index(roll)
                    student_name = (
                        " ".join(parts[1:roll_index]).strip()
                        if roll_index > 1
                        else "N/A"
                    )

                    roll_data[roll] = {
                        "page": page_number,
                        "student": student_name,
                        "college": page_college,
                        "venue": page_venue,
                    }

    return roll_data


def extract_pdf_data(pdf_path):
    roll_data = parse_single_pdf(pdf_path)

    if len(roll_data) == 0:
        try:
            images = convert_from_path(pdf_path)
            for page_num, image in enumerate(images, start=1):
                ocr_text = pytesseract.image_to_string(image)
                lines = [l.strip() for l in ocr_text.split("\n") if l.strip()]
                for line in lines:
                    match = re.search(r"\b\d{6}\b", line)
                    if match:
                        roll = match.group(0)
                        roll_data[roll] = {
                            "page": page_num,
                            "student": "OCR Student",
                            "college": "OCR Extracted",
                            "venue": "OCR Extracted",
                        }
        except Exception as e:
            print(f"OCR Error: {e}")

    return roll_data
