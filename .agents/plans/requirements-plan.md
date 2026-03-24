# Task: `requirements.txt`

## Goal

Create `requirements.txt` with all Phase 1 dependencies so the project environment can be installed in one command.

---

## Task

### CREATE `requirements.txt`

```
fastapi>=0.115.0
uvicorn[standard]>=0.30.0
sqlalchemy>=2.0.0
aiosqlite>=0.20.0
alembic>=1.13.0
pydantic-settings>=2.0.0
python-dotenv>=1.0.0
imapclient>=3.0.0
html2text>=2024.2.26
beautifulsoup4>=4.12.0
lxml>=5.0.0
anthropic>=0.40.0
sentence-transformers>=3.0.0
torch>=2.0.0
weasyprint>=62.0
```

- **GOTCHA:** On Linux servers, `torch` will download the 2GB CUDA build by default. Use `--index-url https://download.pytorch.org/whl/cpu` to get the CPU-only build. On macOS, `pip install torch` defaults to CPU.
- **GOTCHA:** `pydantic-settings` is a separate package from `pydantic` — both are needed but only `pydantic-settings` needs to be listed (it pulls in `pydantic`).

---

## Validation

```bash
pip install -r requirements.txt
python -c "import fastapi, sqlalchemy, imapclient, anthropic, sentence_transformers; print('all imports OK')"
```
