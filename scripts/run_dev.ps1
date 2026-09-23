# Start the PDOS backend server
# Uses SQLite by default (DATABASE_URL commented out in .env)
# For PostgreSQL: uncomment DATABASE_URL in .env first

$env:CORS_ORIGINS="*"
uvicorn main:app --host 0.0.0.0 --port 8000 --reload --log-level info
