"""Extract a skill/role profile from resume text and score jobs against it."""
import re

# Curated vocabulary of tech skills & roles. Matching is done against the
# resume text, so only terms you actually have end up in your profile.
SKILLS = [
    # languages
    "python", "java", "javascript", "typescript", "golang", "go", "rust",
    "c++", "c#", "ruby", "php", "kotlin", "swift", "scala", "r", "matlab",
    "sql", "html", "css", "bash", "dart", "objective-c", "perl", "elixir",
    # frontend
    "react", "react native", "next.js", "nextjs", "vue", "nuxt", "angular",
    "svelte", "redux", "tailwind", "webpack", "vite", "flutter", "electron",
    # backend / frameworks
    "node.js", "nodejs", "express", "nestjs", "django", "flask", "fastapi",
    "spring", "spring boot", "rails", "laravel", ".net", "graphql", "grpc",
    "rest api", "microservices", "websocket",
    # data / ml
    "machine learning", "deep learning", "nlp", "computer vision", "llm",
    "generative ai", "genai", "pytorch", "tensorflow", "keras", "scikit-learn",
    "pandas", "numpy", "spark", "hadoop", "kafka", "airflow", "dbt",
    "data engineering", "data science", "data analysis", "etl", "power bi",
    "tableau", "langchain", "rag", "hugging face", "openai", "anthropic",
    "prompt engineering", "mlops", "xgboost", "opencv", "fine-tuning",
    "vector database", "chatbot", "conversational ai", "dialogflow", "rasa",
    # databases
    "postgresql", "postgres", "mysql", "mongodb", "redis", "elasticsearch",
    "dynamodb", "cassandra", "sqlite", "oracle", "snowflake", "bigquery",
    "clickhouse", "neo4j", "supabase", "firebase",
    # cloud / devops
    "aws", "azure", "gcp", "google cloud", "docker", "kubernetes", "k8s",
    "terraform", "ansible", "jenkins", "ci/cd", "github actions", "gitlab",
    "linux", "nginx", "serverless", "lambda", "cloudformation", "helm",
    "prometheus", "grafana", "devops", "sre",
    # mobile
    "android", "ios", "mobile development",
    # qa / other
    "selenium", "cypress", "playwright", "pytest", "jest", "automation testing",
    "qa", "test automation", "api testing",
    # practices / roles
    "agile", "scrum", "jira", "git", "system design", "distributed systems",
    "product management", "project management", "ui/ux", "figma",
    "cybersecurity", "penetration testing", "blockchain", "solidity",
    "web3", "iot", "embedded", "salesforce", "sap", "servicenow",
    "full stack", "fullstack", "frontend", "front end", "backend", "back end",
]

ROLES = [
    "software engineer", "software developer", "senior software engineer",
    "full stack developer", "fullstack developer", "frontend developer",
    "front end developer", "backend developer", "back end developer",
    "web developer", "mobile developer", "android developer", "ios developer",
    "data scientist", "data engineer", "data analyst", "business analyst",
    "machine learning engineer", "ml engineer", "ai engineer",
    "devops engineer", "site reliability engineer", "cloud engineer",
    "platform engineer", "security engineer", "qa engineer", "sdet",
    "test engineer", "automation engineer", "product manager",
    "project manager", "engineering manager", "tech lead", "team lead",
    "solutions architect", "software architect", "python developer",
    "java developer", "react developer", "node developer", "golang developer",
    "conversational ai engineer", "nlp engineer", "prompt engineer",
    "research engineer", "intern", "graduate engineer",
]


def _find_terms(text: str, vocab: list) -> list:
    text_l = text.lower()
    found = []
    for term in vocab:
        # word-boundary match, tolerant of ./+/# in terms
        pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
        if re.search(pattern, text_l):
            found.append(term)
    return found


def extract_profile(resume_text: str, extra_keywords=None) -> dict:
    skills = _find_terms(resume_text, SKILLS)
    roles = _find_terms(resume_text, ROLES)
    for kw in (extra_keywords or []):
        kw = kw.lower().strip()
        if kw and kw not in skills:
            skills.append(kw)
    # Years of experience, best-effort
    m = re.search(r"(\d+(?:\.\d+)?)\s*\+?\s*years?", resume_text.lower())
    years = float(m.group(1)) if m else None
    return {"skills": skills, "roles": roles, "years": years}


# ------------------------------------------------------------ focus categories
# Every job is classified into one of these buckets so the dashboard can focus
# on Software Engineering / DevOps / AI-ML roles and boost their scores.

CATEGORY_TERMS = {
    "aiml": [
        "machine learning", "ml engineer", "ai engineer", "ai/ml",
        "artificial intelligence", "deep learning", "llm", "genai",
        "generative ai", "nlp", "computer vision", "data scientist",
        "pytorch", "tensorflow", "mlops", "langchain", "rag",
        "prompt engineer", "research engineer", "conversational ai",
        "ai agent", "agentic", "fine-tuning", "hugging face",
    ],
    "devops": [
        "devops", "site reliability", "sre", "platform engineer",
        "infrastructure engineer", "kubernetes", "terraform",
        "cloud engineer", "ci/cd", "cloud architect", "systems engineer",
        "release engineer", "build engineer", "observability",
    ],
    "swe": [
        "software engineer", "software developer", "full stack", "fullstack",
        "backend", "back end", "frontend", "front end", "web developer",
        "sde", "swe", "application engineer", "python developer",
        "java developer", "node", "react", "golang", "api developer",
        "mobile developer", "programmer",
    ],
}

CATEGORY_LABELS = {"swe": "Software Eng", "devops": "DevOps",
                   "aiml": "AI / ML", "other": "Other"}


def categorize(job: dict) -> str:
    """Best-scoring category by weighted keyword hits (title 3, tags 2, desc 1)."""
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    tags = " ".join(job.get("tags") or []).lower()
    best, best_pts = "other", 0
    for cat in ("aiml", "devops", "swe"):  # most specific first — wins ties
        pts = 0
        for term in CATEGORY_TERMS[cat]:
            pattern = r"(?<![a-z0-9])" + re.escape(term) + r"(?![a-z0-9])"
            if re.search(pattern, title):
                pts += 3
            elif re.search(pattern, tags):
                pts += 2
            elif re.search(pattern, desc):
                pts += 1
        if pts > best_pts:
            best, best_pts = cat, pts
    return best


def default_queries(profile: dict, focus=None) -> list:
    """Search queries for boards that need one (LinkedIn, Naukri, Adzuna...).
    Anchored on the focus areas, enriched with roles found in the resume."""
    focus_queries = {
        "swe": ["software engineer"],
        "devops": ["devops engineer"],
        "aiml": ["machine learning engineer", "ai engineer"],
    }
    queries = []
    for f in (focus or ["swe", "devops", "aiml"]):
        queries += focus_queries.get(f, [])
    for role in profile["roles"]:
        if role not in queries and len(queries) < 6:
            queries.append(role)
    return queries or ["software engineer"]


def score_job(profile: dict, job: dict, focus=None) -> tuple:
    """Returns (score, matched_keywords, category). Transparent points system:
    role match in title +6, skill in title +3, skill in tags +2, skill in
    description +1, job in a focus category (swe/devops/aiml) +4."""
    title = (job.get("title") or "").lower()
    desc = (job.get("description") or "").lower()
    tags = " ".join(job.get("tags") or []).lower()
    score = 0
    matched = []

    for role in profile["roles"]:
        if role in title:
            score += 6
            matched.append(role)
            break  # only best role counts

    for skill in profile["skills"]:
        pattern = r"(?<![a-z0-9])" + re.escape(skill) + r"(?![a-z0-9])"
        pts = 0
        if re.search(pattern, title):
            pts = 3
        elif re.search(pattern, tags):
            pts = 2
        elif re.search(pattern, desc):
            pts = 1
        if pts:
            score += pts
            matched.append(skill)

    category = categorize(job)
    if category in (focus or ["swe", "devops", "aiml"]):
        score += 4
    return score, matched, category
