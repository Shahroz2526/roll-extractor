import pytesseract
from pdf2image import convert_from_path

# Tesseract executable path setting
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def extract_pdf_data_ocr(pdf_path):
    """
    Fallback OCR parser function for scanned PDFs.
    Extracted text using PyTesseract if primary PDF parser yields no results.
    """
    roll_data = {}
    try:
        images = convert_from_path(pdf_path)
        for page_number, image in enumerate(images, start=1):
            text = pytesseract.image_to_string(image)
            lines = [l.strip() for l in text.split("\n") if l.strip()]

            # Simple text line parsing for roll numbers and student details
            for line in lines:
                # Basic check for roll numbers or structured rows if needed
                pass

    except Exception as e:
        print(f"OCR Parser Fallback Error: {e}")

    return roll_data
