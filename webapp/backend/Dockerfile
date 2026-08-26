FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . ./

# Railway receives webapp/backend as its entire build context. Fail the image
# build instead of silently running with only the emergency HK$200k ceiling if
# deployment staging forgot the salary table or copied an incomplete package.
RUN python -c "from hk_jobs import salary_anchors; assert salary_anchors.TABLES and salary_anchors.LADDERS, 'salary anchor runtime missing from deployment'"

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
