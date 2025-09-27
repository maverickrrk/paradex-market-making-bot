# FILE: src/utils/config_loader.py

import yaml
import csv
import os
from typing import Dict, List, Any
from dotenv import load_dotenv
from pathlib import Path

# Define a custom exception for better error handling
class ConfigError(Exception):
    """Custom exception for configuration loading errors."""
    pass

def load_main_config(path: str = "config/main_config.yaml") -> Dict[str, Any]:
    """
    Loads the main YAML configuration file.

    Args:
        path: The file path to the main_config.yaml file.

    Returns:
        A dictionary containing the parsed configuration.

    Raises:
        ConfigError: If the file is not found or cannot be parsed.
    """
    if not os.path.exists(path):
        raise ConfigError(f"Main configuration file not found at: {path}")
    
    try:
        with open(path, "r") as f:
            config = yaml.safe_load(f)
        if not config:
            raise ConfigError("Main configuration file is empty or malformed.")
        return config
    except yaml.YAMLError as e:
        raise ConfigError(f"Error parsing YAML configuration file: {e}")
    except Exception as e:
        raise ConfigError(f"An unexpected error occurred while loading main config: {e}")

def load_wallets(path: str = "config/wallets.csv") -> Dict[str, Dict[str, str]]:
    """
    Loads wallet credentials from the specified CSV file.

    The CSV file must have a header and the following columns:
    'wallet_name', 'l1_address', 'l1_private_key'

    Args:
        path: The file path to the wallets.csv file.

    Returns:
        A dictionary where keys are wallet names and values are dicts
        containing 'l1_address' and 'l1_private_key'.

    Raises:
        ConfigError: If the file is not found, is empty, has a missing header,
                     or if a row has an incorrect number of columns.
    """
    if not os.path.exists(path):
        raise ConfigError(
            f"Wallet credentials file not found at: {path}. "
            "Please create it based on the README instructions."
        )

    wallets = {}
    try:
        with open(path, "r", newline="") as f:
            # Skip commented lines
            lines = (line for line in f if not line.strip().startswith('#'))
            reader = csv.reader(lines)
            
            # Read header and validate
            header = next(reader, None)
            expected_header = ["wallet_name", "l1_address", "l1_private_key"]
            if not header or [h.strip() for h in header] != expected_header:
                raise ConfigError(
                    f"Invalid or missing header in {path}. "
                    f"Expected: {', '.join(expected_header)}"
                )

            # Read wallet data
            for i, row in enumerate(reader, start=2):
                if not row or all(not field.strip() for field in row):  # Skip empty lines
                    continue
                if len(row) != 3:
                    raise ConfigError(
                        f"Incorrect number of columns in {path} at line {i}. "
                        f"Expected 3, found {len(row)}."
                    )
                
                wallet_name, l1_address, l1_private_key = [field.strip() for field in row]
                
                if not all([wallet_name, l1_address, l1_private_key]):
                    raise ConfigError(f"Missing data in {path} at line {i}. All fields are required.")

                if not l1_private_key.startswith("0x"):
                     raise ConfigError(f"Invalid l1_private_key for '{wallet_name}' in {path} at line {i}. It must start with '0x'.")

                if wallet_name in wallets:
                    raise ConfigError(f"Duplicate wallet_name '{wallet_name}' found in {path}.")

                wallets[wallet_name] = {
                    "l1_address": l1_address,
                    "l1_private_key": l1_private_key,
                }
        
        if not wallets:
            raise ConfigError(f"No wallets found in {path}. The file cannot be empty.")
            
        return wallets
    except StopIteration:
        raise ConfigError(f"The wallet file at {path} appears to be empty or contains only a header.")
    except Exception as e:
        if isinstance(e, ConfigError):
            raise
        raise ConfigError(f"An unexpected error occurred while loading wallets: {e}")

def load_env_vars() -> Dict[str, str]:
    """
    Loads environment variables from a .env file.

    Returns:
        A dictionary with the required environment variables.

    Raises:
        ConfigError: If the required PARADEX_ENV variable is not set.
    """
    # Force loading .env from the project root directory
    project_root = Path(__file__).parent.parent.parent
    dotenv_path = project_root / '.env'
    
    if not dotenv_path.exists():
        # Fallback for running tests or scripts from different directories
        if os.path.exists('.env'):
            dotenv_path = '.env'
        else:
            raise ConfigError(
                f"The .env file was not found at the project root: {dotenv_path}"
            )
        
    load_dotenv(dotenv_path=dotenv_path)
    
    paradex_env = os.getenv("PARADEX_ENV")
    
    if not paradex_env or paradex_env.lower() not in ['testnet', 'mainnet']:
        raise ConfigError(
            "The 'PARADEX_ENV' environment variable is not set or is invalid. "
            "Please create a .env file and set PARADEX_ENV to 'testnet' or 'mainnet'."
        )
    
    return {"PARADEX_ENV": paradex_env.lower()}