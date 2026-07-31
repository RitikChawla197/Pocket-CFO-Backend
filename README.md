# Personal CFO AI - Backend API

FastAPI backend providing authentication, SQLite database storage, and Google Gemini / Anthropic Claude API integration.

## Local Setup & Running

```bash
# Navigate to backend folder
cd backend

# Install dependencies
pip install -r requirements.txt

# Run the FastAPI dev server on port 8000
python main.py
# OR
uvicorn main:app --reload --port 8000
```

## API Documentation
Once running, interactive API docs are available at:
`http-[#]127.0.0.1:8000/docs`
