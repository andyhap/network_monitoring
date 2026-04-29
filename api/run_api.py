import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import uvicorn
from dotenv import load_dotenv
load_dotenv()

if __name__ == '__main__':
    host = os.getenv('API_HOST', '0.0.0.0')
    port = int(os.getenv('API_PORT', 8000))
    uvicorn.run(
        "api.main_api:app",
        host=host,
        port=port,
        reload=False,
        log_level="info"
    )