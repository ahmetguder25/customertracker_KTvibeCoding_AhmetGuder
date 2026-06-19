import subprocess
import sys
import time
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

def main():
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
            # If process exits, we should exit the whole runner
            if flask_process.poll() is not None:
                break
    except KeyboardInterrupt:
        print("\nShutting down gracefully...")
    finally:
        flask_process.terminate()
        flask_process.wait()
        print("Shutdown complete.")

if __name__ == '__main__':
    main()
