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

    The CSV file must have a header with at least the following columns:
    'wallet_name', 'l1_address', 'l1_private_key'

    Optional columns for Paradex sub-accounts and hedge exchange credentials:
    - 'paradex_sub_account_id', 'paradex_sub_api_key', 'paradex_sub_api_secret'
    - 'hedge_exchange', 'hedge_api_key', 'hedge_api_secret'

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
            header = [h.strip() for h in header] if header else []
            required_header = ["wallet_name", "l1_address", "l1_private_key"]
            if not header or any(col not in header for col in required_header):
                raise ConfigError(
                    f"Invalid or missing header in {path}. "
                    f"Required columns: {', '.join(required_header)}"
                )

            # Read wallet data
            for i, row in enumerate(reader, start=2):
                if not row or all(not field.strip() for field in row):  # Skip empty lines
                    continue
                # Map row to dict by header names (supports optional columns)
                row_values = [field.strip() for field in row]
                row_dict = {header[idx]: row_values[idx] for idx in range(min(len(header), len(row_values)))}

                wallet_name = row_dict.get("wallet_name", "")
                l1_address = row_dict.get("l1_address", "")
                l1_private_key = row_dict.get("l1_private_key", "")
                
                if not all([wallet_name, l1_address, l1_private_key]):
                    raise ConfigError(f"Missing data in {path} at line {i}. All fields are required.")

                if wallet_name in wallets:
                    raise ConfigError(f"Duplicate wallet_name '{wallet_name}' found in {path}.")

                wallet_entry = {
                    "l1_address": l1_address,
                    "l1_private_key": l1_private_key,
                }

                # Optional sub-account fields
                if "paradex_sub_account_id" in row_dict:
                    wallet_entry["paradex_sub_account_id"] = row_dict.get("paradex_sub_account_id", "")
                if "paradex_sub_api_key" in row_dict:
                    wallet_entry["paradex_sub_api_key"] = row_dict.get("paradex_sub_api_key", "")
                if "paradex_sub_api_secret" in row_dict:
                    wallet_entry["paradex_sub_api_secret"] = row_dict.get("paradex_sub_api_secret", "")

                # Optional hedge exchange fields
                if "hedge_exchange" in row_dict:
                    wallet_entry["hedge_exchange"] = row_dict.get("hedge_exchange", "")
                if "hedge_api_key" in row_dict:
                    wallet_entry["hedge_api_key"] = row_dict.get("hedge_api_key", "")
                if "hedge_api_secret" in row_dict:
                    wallet_entry["hedge_api_secret"] = row_dict.get("hedge_api_secret", "")

                wallets[wallet_name] = wallet_entry
        
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
        raise ConfigError(
            f"The .env file was not found at the expected location: {dotenv_path}"
        )
        
    load_dotenv(dotenv_path=dotenv_path)
    
    # Paradex
    paradex_env = os.getenv("PARADEX_ENV")
    paradex_ws_url = os.getenv("PARADEX_WS_URL", "wss://ws.api.prod.paradex.trade/v1")
    
    # Hyperliquid
    hyperliquid_private_key = os.getenv("HYPERLIQUID_PRIVATE_KEY", "")
    hyperliquid_public_address = os.getenv("HYPERLIQUID_PUBLIC_ADDRESS", "")
    hyperliquid_rest_url = os.getenv("HYPERLIQUID_REST_URL", "https://api.hyperliquid.xyz")
    hyperliquid_ws_url = os.getenv("HYPERLIQUID_WS_URL", "")
    hyperliquid_order_endpoint = os.getenv("HYPERLIQUID_ORDER_ENDPOINT", "/exchange")

    # Lighter (NEW)
    lighter_private_key = os.getenv("LIGHTER_PRIVATE_KEY", "")
    lighter_public_address = os.getenv("LIGHTER_PUBLIC_ADDRESS", "")
    lighter_rest_url = os.getenv("LIGHTER_REST_URL", "https://mainnet.zklighter.elliot.ai")
    lighter_is_testnet = os.getenv("LIGHTER_IS_TESTNET", "false")
    
    if not paradex_env:
        raise ConfigError(
            "The 'PARADEX_ENV' environment variable is not set. "
            "Please create a .env file and set PARADEX_ENV to 'testnet' or 'mainnet'."
        )
    
    # Add a print statement for definitive proof
    print(f"--- Successfully loaded environment: PARADEX_ENV = {paradex_env} ---")
    
    return {
        "PARADEX_ENV": paradex_env,
        "PARADEX_WS_URL": paradex_ws_url,
        "HYPERLIQUID_PRIVATE_KEY": hyperliquid_private_key,
        "HYPERLIQUID_PUBLIC_ADDRESS": hyperliquid_public_address,
        "HYPERLIQUID_REST_URL": hyperliquid_rest_url,
        "HYPERLIQUID_WS_URL": hyperliquid_ws_url,
        "HYPERLIQUID_ORDER_ENDPOINT": hyperliquid_order_endpoint,
        "LIGHTER_PRIVATE_KEY": lighter_private_key,
        "LIGHTER_PUBLIC_ADDRESS": lighter_public_address,
        "LIGHTER_REST_URL": lighter_rest_url,
        "LIGHTER_IS_TESTNET": lighter_is_testnet,
    }