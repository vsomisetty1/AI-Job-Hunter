"""Skill normalisation and extraction.

* `normalize_skill("postgres")` -> "PostgreSQL" (known aliases), otherwise the
  cleaned original spelling.
* `find_skills(text)` finds known skills mentioned in free text (bullets,
  summaries). Ambiguous names ("Go", "R", "Swift", "Spring", ...) are only
  accepted from explicit skills lists, never mined from prose.
* `split_skill_list("Python, Go / Rust; CI/CD")` splits a skills line.

The taxonomy is deliberately broad rather than deep; unknown skills from
explicit skills sections are kept as written.
"""

import re
from functools import lru_cache

# canonical name -> aliases (lower case; the canonical name is an alias too)
TAXONOMY: dict[str, list[str]] = {
    # languages
    "Python": ["python", "python3"], "Java": ["java"], "JavaScript": ["javascript", "js", "ecmascript"],
    "TypeScript": ["typescript", "ts"], "Go": ["go", "golang"], "Rust": ["rust"], "C": ["c"],
    "C++": ["c++", "cpp"], "C#": ["c#", "csharp"], "Ruby": ["ruby"], "PHP": ["php"],
    "Kotlin": ["kotlin"], "Swift": ["swift"], "Objective-C": ["objective-c", "objc"],
    "Scala": ["scala"], "R": ["r"], "MATLAB": ["matlab"], "Perl": ["perl"], "Elixir": ["elixir"],
    "Haskell": ["haskell"], "Clojure": ["clojure"], "Dart": ["dart"], "Lua": ["lua"],
    "SQL": ["sql"], "Bash": ["bash", "shell scripting", "shell"], "PowerShell": ["powershell"],
    "HTML": ["html", "html5"], "CSS": ["css", "css3"], "Solidity": ["solidity"],
    # web / frameworks
    "React": ["react", "react.js", "reactjs"], "Next.js": ["next.js", "nextjs"],
    "Vue.js": ["vue", "vue.js", "vuejs"], "Angular": ["angular", "angularjs"],
    "Svelte": ["svelte"], "Node.js": ["node", "node.js", "nodejs"], "Express": ["express", "express.js"],
    "Django": ["django"], "Flask": ["flask"], "FastAPI": ["fastapi"], "Spring": ["spring"],
    "Spring Boot": ["spring boot"], "Ruby on Rails": ["rails", "ruby on rails"],
    ".NET": [".net", "dotnet", ".net core", "asp.net"], "Laravel": ["laravel"],
    "GraphQL": ["graphql"], "REST APIs": ["rest", "restful", "rest api", "rest apis"],
    "gRPC": ["grpc"], "Tailwind CSS": ["tailwind", "tailwindcss", "tailwind css"],
    "Redux": ["redux"], "jQuery": ["jquery"], "React Native": ["react native"],
    "Flutter": ["flutter"],
    # data / ml
    "Pandas": ["pandas"], "NumPy": ["numpy"], "scikit-learn": ["scikit-learn", "sklearn"],
    "TensorFlow": ["tensorflow"], "PyTorch": ["pytorch", "torch"], "Keras": ["keras"],
    "Spark": ["spark", "apache spark", "pyspark"], "Hadoop": ["hadoop"],
    "Kafka": ["kafka", "apache kafka"], "Airflow": ["airflow", "apache airflow"],
    "dbt": ["dbt"], "Snowflake": ["snowflake"], "BigQuery": ["bigquery"],
    "Redshift": ["redshift"], "Databricks": ["databricks"], "Tableau": ["tableau"],
    "Power BI": ["power bi", "powerbi"], "Looker": ["looker"], "Excel": ["excel", "ms excel"],
    "Machine Learning": ["machine learning", "ml"], "Deep Learning": ["deep learning"],
    "NLP": ["nlp", "natural language processing"], "Computer Vision": ["computer vision"],
    "LLMs": ["llm", "llms", "large language models"], "Statistics": ["statistics"],
    "Data Analysis": ["data analysis"], "ETL": ["etl", "elt"], "A/B Testing": ["a/b testing", "ab testing"],
    # databases
    "PostgreSQL": ["postgresql", "postgres", "psql"], "MySQL": ["mysql"], "SQLite": ["sqlite"],
    "MongoDB": ["mongodb", "mongo"], "Redis": ["redis"], "Elasticsearch": ["elasticsearch", "elastic search"],
    "Cassandra": ["cassandra"], "DynamoDB": ["dynamodb"], "Oracle": ["oracle", "oracle db"],
    "SQL Server": ["sql server", "mssql", "ms sql"], "Neo4j": ["neo4j"],
    # cloud / devops
    "AWS": ["aws", "amazon web services"], "GCP": ["gcp", "google cloud", "google cloud platform"],
    "Azure": ["azure", "microsoft azure"], "Docker": ["docker"], "Kubernetes": ["kubernetes", "k8s"],
    "Terraform": ["terraform"], "Ansible": ["ansible"], "Helm": ["helm"],
    "CI/CD": ["ci/cd", "cicd", "continuous integration"], "Jenkins": ["jenkins"],
    "GitHub Actions": ["github actions"], "GitLab CI": ["gitlab ci"], "Git": ["git"],
    "Linux": ["linux", "unix"], "Nginx": ["nginx"], "Prometheus": ["prometheus"],
    "Grafana": ["grafana"], "Datadog": ["datadog"], "Serverless": ["serverless"],
    "AWS Lambda": ["lambda", "aws lambda"], "Microservices": ["microservices", "microservice"],
    "RabbitMQ": ["rabbitmq"], "OpenTelemetry": ["opentelemetry"],
    # testing / practices
    "Agile": ["agile"], "Scrum": ["scrum"], "TDD": ["tdd", "test-driven development"],
    "Jest": ["jest"], "Cypress": ["cypress"], "Playwright": ["playwright"],
    "Selenium": ["selenium"], "pytest": ["pytest"], "JUnit": ["junit"],
    # design / product / business
    "Figma": ["figma"], "Sketch": ["sketch"], "Adobe Photoshop": ["photoshop", "adobe photoshop"],
    "UX Research": ["ux research", "user research"], "Product Management": ["product management"],
    "Jira": ["jira"], "Confluence": ["confluence"], "Salesforce": ["salesforce"],
    "SEO": ["seo"], "Google Analytics": ["google analytics"], "HubSpot": ["hubspot"],
    "Project Management": ["project management"], "Stakeholder Management": ["stakeholder management"],
    "Financial Modeling": ["financial modeling", "financial modelling"],
    # security
    "Penetration Testing": ["penetration testing", "pentesting"], "OAuth": ["oauth", "oauth2"],
    "Cryptography": ["cryptography"], "SIEM": ["siem"],
}  # fmt: skip

# Too ambiguous to mine from prose; accepted only from explicit skills lists.
AMBIGUOUS = {
    "go", "r", "c", "swift", "spring", "rust", "dart", "lua", "express", "react", "node",
    "rest", "shell", "ml", "ts", "js", "oracle", "lambda", "torch", "spark", "agile",
    "excel", "sketch", "flask", "helm", "statistics", "unix", "git",
}  # fmt: skip

_SPLIT = re.compile(r"\s*(?:[,;|•·●▪]|\s/\s|\s-\s|\band\b(?=\s+[A-Z]))\s*")
_CATEGORY = re.compile(r"^\s*([A-Za-z][A-Za-z &/+-]{1,40}?)\s*:\s*(.+)$")
_PARENS = re.compile(r"\s*\(([^)]*)\)")


@lru_cache(maxsize=1)
def _alias_index() -> dict[str, str]:
    index = {}
    for canonical, aliases in TAXONOMY.items():
        for alias in [canonical.lower(), *aliases]:
            index[alias] = canonical
    return index


@lru_cache(maxsize=1)
def _mining_pattern() -> re.Pattern[str]:
    aliases = [a for a in _alias_index() if a not in AMBIGUOUS]
    aliases.sort(key=len, reverse=True)  # prefer "spring boot" over "spring"
    body = "|".join(re.escape(a) for a in aliases)
    return re.compile(rf"(?<![\w+#.])(?:{body})(?![\w+#]|\.\w)", re.IGNORECASE)


def clean_skill(raw: str) -> str:
    s = raw.strip().strip(".,;:").strip()
    s = re.sub(r"\s+", " ", s)
    return s


def normalize_skill(raw: str) -> str:
    s = clean_skill(raw)
    return _alias_index().get(s.lower(), s)


def is_known_skill(raw: str) -> bool:
    return clean_skill(raw).lower() in _alias_index()


def split_skill_list(line: str) -> tuple[str | None, list[str]]:
    """("Languages", ["Python", "Go"]) for "Languages: Python, Go"; category may be None."""
    category = None
    m = _CATEGORY.match(line)
    if m and len(m.group(1).split()) <= 4:
        category, line = m.group(1).strip(), m.group(2)
    # "Python (Django, Flask)" -> Python, Django, Flask
    line = _PARENS.sub(lambda mm: ", " + mm.group(1), line)
    parts = [clean_skill(p) for p in _SPLIT.split(line)]
    skills = [p for p in parts if p and len(p) <= 60 and len(p.split()) <= 6]
    return category, skills


def find_skills(text: str) -> list[str]:
    """Known, unambiguous skills mentioned in free text, in order of first mention."""
    found: dict[str, None] = {}
    index = _alias_index()
    for m in _mining_pattern().finditer(text):
        found.setdefault(index[m.group(0).lower()], None)
    return list(found)


def dedupe_skills(skills: list[str]) -> list[str]:
    out: dict[str, str] = {}
    for s in skills:
        norm = normalize_skill(s)
        if norm:
            out.setdefault(norm.lower(), norm)
    return list(out.values())
