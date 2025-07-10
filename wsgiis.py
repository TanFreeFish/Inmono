import uvicorn
from app_inksync import app

if __name__ == '__main__':
    uvicorn.run("app_inksync:app", host="0.0.0.0", port=8000, reload=True)
