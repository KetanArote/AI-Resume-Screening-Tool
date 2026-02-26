from flask import Flask, request, render_template
import os
import docx2txt
import PyPDF2
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from groq import Groq
from google import genai
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

# --------------------------------------------------
# SETUP
# --------------------------------------------------

load_dotenv()

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = "uploads"

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

MAX_RESUME_CHARS = 4000   # safety limit for LLM


# --------------------------------------------------
# TEXT EXTRACTION
# --------------------------------------------------

def extract_text_from_pdf(path):
    text = ""
    with open(path, "rb") as f:
        reader = PyPDF2.PdfReader(f)
        for page in reader.pages:
            if page.extract_text():
                text += page.extract_text()
    return text


def extract_text_from_docx(path):
    return docx2txt.process(path)


def extract_text_from_txt(path):
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def extract_text(path):
    if path.endswith(".pdf"):
        return extract_text_from_pdf(path)
    if path.endswith(".docx"):
        return extract_text_from_docx(path)
    if path.endswith(".txt"):
        return extract_text_from_txt(path)
    return ""


# --------------------------------------------------
# AI FEEDBACK (GROQ)
# --------------------------------------------------

def ai_resume_feedback(job_description, resume_text, score):
    try:
        prompt = f"""
You are an AI resume screening assistant used by recruiters.

Job Description:
{job_description}

Resume:
{resume_text}

Similarity Score: {score:.2f}%

STRICT INSTRUCTIONS:
- Respond in MAX 6 bullet points
- Each bullet ≤ 15 words
- Professional, recruiter-style tone
- No explanations, no paragraphs
- No repetition

FORMAT EXACTLY LIKE THIS:
• Overall: <short assessment>
• Strengths: <key strengths>
• Gaps: <key missing skills>
• Recommendation: <1-line improvement>
"""


        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "You are a professional ATS resume evaluator."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.2,   # lower = more controlled
            max_tokens=120     # HARD limit
        )

        return response.choices[0].message.content.strip()

    except Exception:
        return "AI feedback unavailable."

# --------------------------------------------------
# ROUTES
# --------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/matcher", methods=["POST"])
def matcher():
    job_description = request.form.get("job_description", "").strip()
    resume_files = request.files.getlist("resumes")

    if not job_description or not resume_files:
        return render_template(
            "index.html",
            message="Please upload resumes and enter a job description."
        )

    resumes = []

    # Save files + extract text
    for file in resume_files:
        filename = secure_filename(file.filename)
        path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        file.save(path)

        text = extract_text(path)[:MAX_RESUME_CHARS]

        resumes.append({
            "filename": filename,
            "text": text
        })

    # TF-IDF + similarity
    resume_texts = [r["text"] for r in resumes]
    vectorizer = TfidfVectorizer(stop_words="english")
    vectors = vectorizer.fit_transform([job_description] + resume_texts).toarray()

    job_vector = vectors[0]
    resume_vectors = vectors[1:]

    similarities = cosine_similarity([job_vector], resume_vectors)[0]

    # Rank top 5
    top_indices = similarities.argsort()[-5:][::-1]

    results = []

    for rank, i in enumerate(top_indices):
        score_percent = round(similarities[i] * 100, 2)

        if rank < 3:
            feedback = ai_resume_feedback(
                job_description,
                resumes[i]["text"],
                score_percent
            )
        else:
            feedback = "AI feedback available for top 3 resumes only."

        results.append({
            "resume": resumes[i]["filename"],
            "score": score_percent,
            "ai_feedback": feedback
        })

    return render_template(
        "index.html",
        message="Top matching resumes:",
        results=results
    )


# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
    app.run(debug=True)
