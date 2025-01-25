import os
from dotenv import load_dotenv
from pathlib import Path


def load_config():
    """
    Load configuration from .env file and validate required keys.
    Returns:
        dict: A dictionary containing the configuration values.
    Raises:
        FileNotFoundError: If the .env file is missing.
        ValueError: If any required key is missing in the .env file.
    """
    # Ensure the .env file exists
    env_path = Path(".env")
    if not env_path.exists():
        raise FileNotFoundError(
            ".env file is missing. Please create it with the following keys:\n"
            "API_ID=your_api_id\n"
            "API_HASH=your_api_hash\n"
            "CHAT_ID=-1001593560584\n"
            "BATCH_SIZE=20\n"
            "OUTPUT_DIR=./output\n"
        )

    # Load environment variables from the .env file
    load_dotenv()

    # Define required configuration keys
    required_keys = ["API_ID", "API_HASH", "CHAT_ID", "BATCH_SIZE", "OUTPUT_DIR"]

    # Load and validate configuration
    config = {}
    for key in required_keys:
        value = os.getenv(key)
        if value is None:
            raise ValueError(f"Missing required configuration key: {key}")
        config[key] = value

    # Convert specific types
    config["BATCH_SIZE"] = int(config["BATCH_SIZE"])  # Ensure BATCH_SIZE is an integer
    config["OUTPUT_DIR"] = Path(config["OUTPUT_DIR"])  # Convert OUTPUT_DIR to a Path object

    # Ensure the output directory exists
    config["OUTPUT_DIR"].mkdir(parents=True, exist_ok=True)

    return config