import subprocess
import sys
import time
import os
from dotenv import load_dotenv
import rag_db

# Load environment variables from .env file
load_dotenv()

def main():
    print("Initializing Database...")
    rag_db.init_db()

    print("Starting Huey Background Worker...")
    # Start the huey consumer in a subprocess
    huey_process = subprocess.Popen(
        [sys.executable, "-m", "huey.bin.huey_consumer", "tasks.huey", "-w", "2"],
        stdout=sys.stdout,
        stderr=sys.stderr
    )

    print("Starting Flask Web Server...")
    # Start the Flask app
    flask_process = subprocess.Popen(
        [sys.executable, "-m", "flask", "run", "--port", "5000"],
        env=dict(os.environ, FLASK_DEBUG="1"),
        stdout=sys.stdout,
        stderr=sys.stderr
    )

    try:
        # Keep the main thread alive waiting for subprocesses
        while True:
            time.sleep(1)
            # If either process exits, we should exit the whole runner
            if flask_process.poll() is not None or huey_process.poll() is not None:
                break
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    finally:
        flask_process.terminate()
        huey_process.terminate()
        flask_process.wait()
        huey_process.wait()
        print("Shutdown complete.")

import os
if __name__ == '__main__':
    main()
