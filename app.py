<<<<<<< HEAD
import os
import re
import pandas as pd
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.utils import secure_filename
from concurrent.futures import ThreadPoolExecutor

# Try importing parsers safely
try:
    from parser import extract_pdf_data
except ImportError:

    def extract_pdf_data(path):
        return {}


try:
    from ocr_parser import extract_pdf_data_ocr
except ImportError:

    def extract_pdf_data_ocr(path):
        return {}


app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
PROCESSED_FOLDER = os.path.join(BASE_DIR, "processed")
STATIC_IMAGES = os.path.join(BASE_DIR, "static", "uploaded_sheets")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROCESSED_FOLDER"] = PROCESSED_FOLDER
app.config["STATIC_IMAGES"] = STATIC_IMAGES
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024

DEPARTMENT_PASSCODE = "1234"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs(STATIC_IMAGES, exist_ok=True)


def process_single_pdf(pdf_file_storage):
    """Parallel worker to process individual PDF files efficiently."""
    filename = secure_filename(pdf_file_storage.filename)
    pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    pdf_file_storage.save(pdf_path)

    data = extract_pdf_data(pdf_path)
    if not data:
        data = extract_pdf_data_ocr(pdf_path)

    subject_clean = os.path.splitext(filename)[0]
    extracted_records = {}
    for r_num, r_info in data.items():
        if isinstance(r_info, dict):
            r_info["pdf_source"] = filename
            r_info["subject_clean"] = subject_clean
            # FIX 1: Safeguard against N/A or empty College/School Name
            college_val = str(r_info.get("college", "")).strip()
            if not college_val or college_val.upper() in ["N/A", "NONE", "NAN", ""]:
                r_info["college"] = subject_clean.replace("_", " ").replace("-", " ")

            extracted_records[r_num] = r_info

    return filename, extracted_records


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        user_passcode = request.form.get("passcode")
        if user_passcode != DEPARTMENT_PASSCODE:
            return render_template(
                "index.html",
                step="1",
                error="🔒 Incorrect Security Passcode. Access Denied.",
            )

        pdf_files = request.files.getlist("pdf_files")
        excel_file = request.files.get("excel_file")

        if not pdf_files or not excel_file or pdf_files[0].filename == "":
            return render_template(
                "index.html",
                step="1",
                error="Please upload at least one valid PDF file and the Master Excel file.",
            )

        combined_pdf_data = {}
        pdf_source_map = {}

        # Parallel PDF Processing for Maximum Performance
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(process_single_pdf, pdf)
                for pdf in pdf_files
                if pdf and pdf.filename.endswith(".pdf")
            ]
            for future in futures:
                fname, records = future.result()
                for r_num, r_info in records.items():
                    combined_pdf_data[r_num] = r_info
                    pdf_source_map[r_num] = fname

        excel_filename = secure_filename(excel_file.filename)
        excel_path = os.path.join(app.config["UPLOAD_FOLDER"], excel_filename)
        excel_file.save(excel_path)

        df = pd.read_excel(excel_path)

        roll_col = next((c for c in df.columns if "ROLL" in str(c).upper()), None)
        candidate_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["CANDIDATE", "STUDENT"])
            ),
            "Candidate",
        )
        school_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["SCHOOL", "COLLEGE"])
            ),
            "School",
        )
        center_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["CENTER", "VENUE"])
            ),
            "Center",
        )
        page_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["PG NO", "PAGE"])
            ),
            "PG NO.",
        )
        script_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["SCRIPT", "SCRIPT#", "SCRIPT NO"])
            ),
            "Script No",
        )
        pdf_col = "PDF_Source"

        for col in [
            candidate_col,
            school_col,
            center_col,
            page_col,
            script_col,
            pdf_col,
        ]:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].astype("object")

        # Counter metrics for the 4 boxes
        total_rows = len(df)
        found_count = 0
        already_exist_count = 0
        not_found_count = 0

        pdf_target_pages = {}
        results = []

        for index_row, row in df.iterrows():
            curr_cand = str(row[candidate_col]).strip()

            # Count already exist / pre-filled rows
            if curr_cand and curr_cand not in ["nan", "None", ""]:
                already_exist_count += 1
                continue

            raw_roll = str(row[roll_col]).strip()
            roll = raw_roll.split(".")[0] if "." in raw_roll else raw_roll

            if roll in combined_pdf_data:
                info = combined_pdf_data[roll]
                clean_page = str(info["page"]).split(".")[0]
                source_pdf = pdf_source_map.get(roll, "PDF Document")

                # Ensure non-empty school name fallback
                final_school = str(info["college"]).strip()
                if not final_school or final_school.upper() in ["N/A", "NONE", "NAN"]:
                    final_school = str(
                        info.get("subject_clean", "School/College")
                    ).replace("_", " ")

                df.at[index_row, candidate_col] = str(info["student"])
                df.at[index_row, school_col] = final_school
                df.at[index_row, center_col] = str(info["venue"])
                df.at[index_row, page_col] = str(clean_page)
                df.at[index_row, pdf_col] = str(source_pdf)

                if clean_page and clean_page != "N/A":
                    if source_pdf not in pdf_target_pages:
                        pdf_target_pages[source_pdf] = set()
                    pdf_target_pages[source_pdf].add(clean_page)

                found_count += 1
                results.append(
                    {
                        "roll": roll,
                        "student": info["student"],
                        "college": final_school,
                        "venue": info["venue"],
                        "page": clean_page,
                        "script_no": (
                            str(row[script_col])
                            if str(row[script_col]) != "nan"
                            else "-"
                        ),
                        "status": "Verified & Mapped",
                    }
                )
            else:
                not_found_count += 1

        pdf_page_groups = {}
        for pdf_name, page_set in pdf_target_pages.items():
            pdf_page_groups[pdf_name] = sorted(
                list(page_set), key=lambda x: int(x) if x.isdigit() else 9999
            )

        output_filename = f"Step1_{excel_filename}"
        output_path = os.path.join(app.config["PROCESSED_FOLDER"], output_filename)
        df.to_excel(output_path, index=False, engine="openpyxl")

        summary_stats = {
            "total": total_rows,
            "found": found_count,
            "not_found": not_found_count,
            "already_exist": already_exist_count,
        }

        return render_template(
            "index.html",
            step="1_completed",
            results=results,
            summary=summary_stats,
            download_file=output_filename,
            pdf_page_groups=pdf_page_groups,
            working_excel=output_filename,
        )

    return render_template("index.html", step="1")


@app.route("/upload-single-image", methods=["POST"])
def upload_single_image():
    working_excel = request.form.get("working_excel")
    subject_key = request.form.get("subject_key", "Subject")
    file = request.files.get("file")

    if not working_excel or not file:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Missing image or reference excel parameters.",
                }
            ),
            400,
        )

    excel_path = os.path.join(app.config["PROCESSED_FOLDER"], working_excel)
    if not os.path.exists(excel_path):
        return (
            jsonify(
                {"status": "error", "message": "Working Excel reference not found."}
            ),
            404,
        )

    df = pd.read_excel(excel_path)
    page_col = next(
        (c for c in df.columns if any(k in str(c).upper() for k in ["PG NO", "PAGE"])),
        "PG NO.",
    )

    needed_pages = set()
    for idx, row in df.iterrows():
        pg_val = str(row[page_col]).strip().split(".")[0]
        if pg_val and pg_val not in ["nan", "N/A"]:
            needed_pages.add(pg_val)

    original_filename = secure_filename(file.filename)
    page_match = re.search(r"\d+", os.path.splitext(original_filename)[0])
    page_num = page_match.group(0) if page_match else None

    if page_num and page_num in needed_pages:
        unique_filename = f"{secure_filename(subject_key)}_pg_{page_num}.jpg"
        save_path = os.path.join(app.config["STATIC_IMAGES"], unique_filename)
        file.save(save_path)
        return jsonify(
            {"status": "saved", "page": page_num, "filename": unique_filename}
        )

    return jsonify(
        {"status": "skipped", "reason": "Page omitted - Not in target list."}
    )


@app.route("/open-input-screen", methods=["POST"])
def open_input_screen():
    working_excel = request.form.get("working_excel")
    excel_path = os.path.join(app.config["PROCESSED_FOLDER"], working_excel)
    df = pd.read_excel(excel_path)

    roll_col = next((c for c in df.columns if "ROLL" in str(c).upper()), None)
    candidate_col = next(
        (
            c
            for c in df.columns
            if any(k in str(c).upper() for k in ["CANDIDATE", "STUDENT"])
        ),
        "Candidate",
    )
    page_col = next(
        (c for c in df.columns if any(k in str(c).upper() for k in ["PG NO", "PAGE"])),
        "PG NO.",
    )
    script_col = next(
        (
            c
            for c in df.columns
            if any(k in str(c).upper() for k in ["SCRIPT", "SCRIPT#", "SCRIPT NO"])
        ),
        "Script No",
    )
    pdf_col = "PDF_Source" if "PDF_Source" in df.columns else None

    df[page_col] = df[page_col].astype(str)
    df[script_col] = df[script_col].astype("object")

    uploaded_files = os.listdir(app.config["STATIC_IMAGES"])

    students_to_input = []
    for idx, row in df.iterrows():
        pg = str(row[page_col]).strip().split(".")[0]
        source_pdf = str(row[pdf_col]) if pdf_col else ""

        matched_img = None
        for f in uploaded_files:
            p_match = re.search(r"_pg_(\d+)\.jpg", f)
            if p_match and p_match.group(1) == pg:
                clean_subj_key = secure_filename(
                    source_pdf.replace(".pdf", "").replace(".PDF", "")
                )
                if clean_subj_key in f or matched_img is None:
                    matched_img = f

        if matched_img:
            students_to_input.append(
                {
                    "row_index": idx,
                    "roll": str(row[roll_col]),
                    "name": str(row[candidate_col]),
                    "page": pg,
                    "image_filename": matched_img,
                    "current_script": (
                        str(row[script_col]) if str(row[script_col]) != "nan" else ""
                    ),
                }
            )

    return render_template(
        "index.html",
        step="guided_input",
        students=students_to_input,
        working_excel=working_excel,
    )


@app.route("/save-guided-scripts", methods=["POST"])
def save_guided_scripts():
    working_excel = request.form.get("working_excel")
    excel_path = os.path.join(app.config["PROCESSED_FOLDER"], working_excel)
    df = pd.read_excel(excel_path)

    script_col = next(
        (
            c
            for c in df.columns
            if any(k in str(c).upper() for k in ["SCRIPT", "SCRIPT#", "SCRIPT NO"])
        ),
        "Script No",
    )
    df[script_col] = df[script_col].astype("object")

    updated_count = 0
    for key, value in request.form.items():
        if key.startswith("script_"):
            row_idx = int(key.split("_")[1])
            val_str = str(value).strip()
            if val_str:
                df.at[row_idx, script_col] = val_str
                updated_count += 1

    final_excel_name = f"Final_Completed_{working_excel.replace('Step1_', '')}"
    final_path = os.path.join(app.config["PROCESSED_FOLDER"], final_excel_name)

    if "PDF_Source" in df.columns:
        df_download = df.drop(columns=["PDF_Source"])
    else:
        df_download = df

    df_download.to_excel(final_path, index=False, engine="openpyxl")

    return render_template(
        "index.html",
        step="2_completed",
        updated_count=updated_count,
        final_download=final_excel_name,
    )


@app.route("/download/<path:filename>")
def download_file(filename):
    return send_from_directory(
        app.config["PROCESSED_FOLDER"], filename, as_attachment=True
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
=======
import os
import re
import pandas as pd
from flask import (
    Flask,
    jsonify,
    render_template,
    request,
    send_from_directory,
)
from werkzeug.utils import secure_filename
from concurrent.futures import ThreadPoolExecutor

# Try importing parsers safely
try:
    from parser import extract_pdf_data
except ImportError:

    def extract_pdf_data(path):
        return {}


try:
    from ocr_parser import extract_pdf_data_ocr
except ImportError:

    def extract_pdf_data_ocr(path):
        return {}


app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
PROCESSED_FOLDER = os.path.join(BASE_DIR, "processed")
STATIC_IMAGES = os.path.join(BASE_DIR, "static", "uploaded_sheets")

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["PROCESSED_FOLDER"] = PROCESSED_FOLDER
app.config["STATIC_IMAGES"] = STATIC_IMAGES
app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024 * 1024

DEPARTMENT_PASSCODE = "1234"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(PROCESSED_FOLDER, exist_ok=True)
os.makedirs(STATIC_IMAGES, exist_ok=True)


def process_single_pdf(pdf_file_storage):
    """Parallel worker to process individual PDF files efficiently."""
    filename = secure_filename(pdf_file_storage.filename)
    pdf_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    pdf_file_storage.save(pdf_path)

    data = extract_pdf_data(pdf_path)
    if not data:
        data = extract_pdf_data_ocr(pdf_path)

    subject_clean = os.path.splitext(filename)[0]
    extracted_records = {}
    for r_num, r_info in data.items():
        if isinstance(r_info, dict):
            r_info["pdf_source"] = filename
            r_info["subject_clean"] = subject_clean
            # FIX 1: Safeguard against N/A or empty College/School Name
            college_val = str(r_info.get("college", "")).strip()
            if not college_val or college_val.upper() in ["N/A", "NONE", "NAN", ""]:
                r_info["college"] = subject_clean.replace("_", " ").replace("-", " ")

            extracted_records[r_num] = r_info

    return filename, extracted_records


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        user_passcode = request.form.get("passcode")
        if user_passcode != DEPARTMENT_PASSCODE:
            return render_template(
                "index.html",
                step="1",
                error="🔒 Incorrect Security Passcode. Access Denied.",
            )

        pdf_files = request.files.getlist("pdf_files")
        excel_file = request.files.get("excel_file")

        if not pdf_files or not excel_file or pdf_files[0].filename == "":
            return render_template(
                "index.html",
                step="1",
                error="Please upload at least one valid PDF file and the Master Excel file.",
            )

        combined_pdf_data = {}
        pdf_source_map = {}

        # Parallel PDF Processing for Maximum Performance
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [
                executor.submit(process_single_pdf, pdf)
                for pdf in pdf_files
                if pdf and pdf.filename.endswith(".pdf")
            ]
            for future in futures:
                fname, records = future.result()
                for r_num, r_info in records.items():
                    combined_pdf_data[r_num] = r_info
                    pdf_source_map[r_num] = fname

        excel_filename = secure_filename(excel_file.filename)
        excel_path = os.path.join(app.config["UPLOAD_FOLDER"], excel_filename)
        excel_file.save(excel_path)

        df = pd.read_excel(excel_path)

        roll_col = next((c for c in df.columns if "ROLL" in str(c).upper()), None)
        candidate_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["CANDIDATE", "STUDENT"])
            ),
            "Candidate",
        )
        school_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["SCHOOL", "COLLEGE"])
            ),
            "School",
        )
        center_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["CENTER", "VENUE"])
            ),
            "Center",
        )
        page_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["PG NO", "PAGE"])
            ),
            "PG NO.",
        )
        script_col = next(
            (
                c
                for c in df.columns
                if any(k in str(c).upper() for k in ["SCRIPT", "SCRIPT#", "SCRIPT NO"])
            ),
            "Script No",
        )
        pdf_col = "PDF_Source"

        for col in [
            candidate_col,
            school_col,
            center_col,
            page_col,
            script_col,
            pdf_col,
        ]:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].astype("object")

        # Counter metrics for the 4 boxes
        total_rows = len(df)
        found_count = 0
        already_exist_count = 0
        not_found_count = 0

        pdf_target_pages = {}
        results = []

        for index_row, row in df.iterrows():
            curr_cand = str(row[candidate_col]).strip()

            # Count already exist / pre-filled rows
            if curr_cand and curr_cand not in ["nan", "None", ""]:
                already_exist_count += 1
                continue

            raw_roll = str(row[roll_col]).strip()
            roll = raw_roll.split(".")[0] if "." in raw_roll else raw_roll

            if roll in combined_pdf_data:
                info = combined_pdf_data[roll]
                clean_page = str(info["page"]).split(".")[0]
                source_pdf = pdf_source_map.get(roll, "PDF Document")

                # Ensure non-empty school name fallback
                final_school = str(info["college"]).strip()
                if not final_school or final_school.upper() in ["N/A", "NONE", "NAN"]:
                    final_school = str(
                        info.get("subject_clean", "School/College")
                    ).replace("_", " ")

                df.at[index_row, candidate_col] = str(info["student"])
                df.at[index_row, school_col] = final_school
                df.at[index_row, center_col] = str(info["venue"])
                df.at[index_row, page_col] = str(clean_page)
                df.at[index_row, pdf_col] = str(source_pdf)

                if clean_page and clean_page != "N/A":
                    if source_pdf not in pdf_target_pages:
                        pdf_target_pages[source_pdf] = set()
                    pdf_target_pages[source_pdf].add(clean_page)

                found_count += 1
                results.append(
                    {
                        "roll": roll,
                        "student": info["student"],
                        "college": final_school,
                        "venue": info["venue"],
                        "page": clean_page,
                        "script_no": (
                            str(row[script_col])
                            if str(row[script_col]) != "nan"
                            else "-"
                        ),
                        "status": "Verified & Mapped",
                    }
                )
            else:
                not_found_count += 1

        pdf_page_groups = {}
        for pdf_name, page_set in pdf_target_pages.items():
            pdf_page_groups[pdf_name] = sorted(
                list(page_set), key=lambda x: int(x) if x.isdigit() else 9999
            )

        output_filename = f"Step1_{excel_filename}"
        output_path = os.path.join(app.config["PROCESSED_FOLDER"], output_filename)
        df.to_excel(output_path, index=False, engine="openpyxl")

        summary_stats = {
            "total": total_rows,
            "found": found_count,
            "not_found": not_found_count,
            "already_exist": already_exist_count,
        }

        return render_template(
            "index.html",
            step="1_completed",
            results=results,
            summary=summary_stats,
            download_file=output_filename,
            pdf_page_groups=pdf_page_groups,
            working_excel=output_filename,
        )

    return render_template("index.html", step="1")


@app.route("/upload-single-image", methods=["POST"])
def upload_single_image():
    working_excel = request.form.get("working_excel")
    subject_key = request.form.get("subject_key", "Subject")
    file = request.files.get("file")

    if not working_excel or not file:
        return (
            jsonify(
                {
                    "status": "error",
                    "message": "Missing image or reference excel parameters.",
                }
            ),
            400,
        )

    excel_path = os.path.join(app.config["PROCESSED_FOLDER"], working_excel)
    if not os.path.exists(excel_path):
        return (
            jsonify(
                {"status": "error", "message": "Working Excel reference not found."}
            ),
            404,
        )

    df = pd.read_excel(excel_path)
    page_col = next(
        (c for c in df.columns if any(k in str(c).upper() for k in ["PG NO", "PAGE"])),
        "PG NO.",
    )

    needed_pages = set()
    for idx, row in df.iterrows():
        pg_val = str(row[page_col]).strip().split(".")[0]
        if pg_val and pg_val not in ["nan", "N/A"]:
            needed_pages.add(pg_val)

    original_filename = secure_filename(file.filename)
    page_match = re.search(r"\d+", os.path.splitext(original_filename)[0])
    page_num = page_match.group(0) if page_match else None

    if page_num and page_num in needed_pages:
        unique_filename = f"{secure_filename(subject_key)}_pg_{page_num}.jpg"
        save_path = os.path.join(app.config["STATIC_IMAGES"], unique_filename)
        file.save(save_path)
        return jsonify(
            {"status": "saved", "page": page_num, "filename": unique_filename}
        )

    return jsonify(
        {"status": "skipped", "reason": "Page omitted - Not in target list."}
    )


@app.route("/open-input-screen", methods=["POST"])
def open_input_screen():
    working_excel = request.form.get("working_excel")
    excel_path = os.path.join(app.config["PROCESSED_FOLDER"], working_excel)
    df = pd.read_excel(excel_path)

    roll_col = next((c for c in df.columns if "ROLL" in str(c).upper()), None)
    candidate_col = next(
        (
            c
            for c in df.columns
            if any(k in str(c).upper() for k in ["CANDIDATE", "STUDENT"])
        ),
        "Candidate",
    )
    page_col = next(
        (c for c in df.columns if any(k in str(c).upper() for k in ["PG NO", "PAGE"])),
        "PG NO.",
    )
    script_col = next(
        (
            c
            for c in df.columns
            if any(k in str(c).upper() for k in ["SCRIPT", "SCRIPT#", "SCRIPT NO"])
        ),
        "Script No",
    )
    pdf_col = "PDF_Source" if "PDF_Source" in df.columns else None

    df[page_col] = df[page_col].astype(str)
    df[script_col] = df[script_col].astype("object")

    uploaded_files = os.listdir(app.config["STATIC_IMAGES"])

    students_to_input = []
    for idx, row in df.iterrows():
        pg = str(row[page_col]).strip().split(".")[0]
        source_pdf = str(row[pdf_col]) if pdf_col else ""

        matched_img = None
        for f in uploaded_files:
            p_match = re.search(r"_pg_(\d+)\.jpg", f)
            if p_match and p_match.group(1) == pg:
                clean_subj_key = secure_filename(
                    source_pdf.replace(".pdf", "").replace(".PDF", "")
                )
                if clean_subj_key in f or matched_img is None:
                    matched_img = f

        if matched_img:
            students_to_input.append(
                {
                    "row_index": idx,
                    "roll": str(row[roll_col]),
                    "name": str(row[candidate_col]),
                    "page": pg,
                    "image_filename": matched_img,
                    "current_script": (
                        str(row[script_col]) if str(row[script_col]) != "nan" else ""
                    ),
                }
            )

    return render_template(
        "index.html",
        step="guided_input",
        students=students_to_input,
        working_excel=working_excel,
    )


@app.route("/save-guided-scripts", methods=["POST"])
def save_guided_scripts():
    working_excel = request.form.get("working_excel")
    excel_path = os.path.join(app.config["PROCESSED_FOLDER"], working_excel)
    df = pd.read_excel(excel_path)

    script_col = next(
        (
            c
            for c in df.columns
            if any(k in str(c).upper() for k in ["SCRIPT", "SCRIPT#", "SCRIPT NO"])
        ),
        "Script No",
    )
    df[script_col] = df[script_col].astype("object")

    updated_count = 0
    for key, value in request.form.items():
        if key.startswith("script_"):
            row_idx = int(key.split("_")[1])
            val_str = str(value).strip()
            if val_str:
                df.at[row_idx, script_col] = val_str
                updated_count += 1

    final_excel_name = f"Final_Completed_{working_excel.replace('Step1_', '')}"
    final_path = os.path.join(app.config["PROCESSED_FOLDER"], final_excel_name)

    if "PDF_Source" in df.columns:
        df_download = df.drop(columns=["PDF_Source"])
    else:
        df_download = df

    df_download.to_excel(final_path, index=False, engine="openpyxl")

    return render_template(
        "index.html",
        step="2_completed",
        updated_count=updated_count,
        final_download=final_excel_name,
    )


@app.route("/download/<path:filename>")
def download_file(filename):
    return send_from_directory(
        app.config["PROCESSED_FOLDER"], filename, as_attachment=True
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)
>>>>>>> 72bbe7b7bda494596cc4f0a6095d50165bc5388c
