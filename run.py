import uvicorn
from config.settings import SERVER_HOST, SERVER_PORT

if __name__ == "__main__":
    uvicorn.run("src.server:app", host=SERVER_HOST, port=SERVER_PORT, reload=True)