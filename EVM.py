"""Export ERC-20 transfers for EVM chains only.

Mirrors ``main.py`` but restricts processing to Ethereum-compatible
chains. Transactions are normalized, priced in USD via CoinGecko and
written to ``transactions.csv`` and ``token_balances.csv``.
"""

import os
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

# --------- LOAD ENV VARIABLES ---------
load_dotenv()

ETH_ADDRESS = os.getenv("ETH_ADDRESS")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

required_vars = {
    "ETH_ADDRESS": ETH_ADDRESS,
    "ETHERSCAN_API_KEY": ETHERSCAN_API_KEY,
    "COINGECKO_API_KEY": COINGECKO_API_KEY,
}
missing = [name for name, value in required_vars.items() if not value]
if missing:
    missing_str = ", ".join(missing)
    raise EnvironmentError(
        f"Missing required environment variables: {missing_str}"
    )

# CHAIN_IDS maps chain names to the IDs used by the Etherscan v2 API
CHAIN_IDS = {
    "ethereum": 1,
    "arbitrum": 42161,
    "polygon": 137,
    "bsc": 56,
    "avalanche": 43114,
}

COINGECKO_API = "https://api.coingecko.com/api/v3/simple/token_price"


def fetch_erc20_transactions(chain: str, address: str, api_key: str):
    """Return ERC-20 token transfers for ``address`` on an EVM ``chain``."""
    chain_id = CHAIN_IDS[chain]
    url = (
        f"https://api.etherscan.io/v2/api?chainid={chain_id}"
        f"&module=account&action=tokentx"
        f"&address={address}&startblock=0&endblock=latest&sort=asc"
        f"&apikey={api_key}"
    )
    resp = requests.get(url)
    data = resp.json()
    if data.get("status") != "1":
        print(f"[!] Pas de données pour {chain}: {data.get('message')}")
        return []
    return data["result"]


def normalize_transactions(transactions, chain):
    """Normalize raw transaction data into a common schema."""
    normalized = []
    for tx in transactions:
        value = int(tx["value"]) / (10 ** int(tx["tokenDecimal"]))
        normalized.append(
            {
                "chain": chain,
                "timestamp": datetime.fromtimestamp(
                    int(tx["timeStamp"]), timezone.utc
                ),
                "hash": tx["hash"],
                "from": tx["from"],
                "to": tx["to"],
                "tokenName": tx["tokenName"],
                "tokenSymbol": tx["tokenSymbol"],
                "contractAddress": tx["contractAddress"].lower(),
                "value": value,
                "direction": (
                    "IN"
                    if tx["to"].lower() == ETH_ADDRESS.lower()
                    else "OUT"
                ),
            }
        )
    return normalized


def get_token_prices(contract_addresses_by_chain):
    """Fetch USD prices for tokens across supported chains."""
    prices = {}
    headers = {
        "accept": "application/json",
        "x-cg-demo-api-key": COINGECKO_API_KEY,
    }
    platform_map = {
        "ethereum": "ethereum",
        "arbitrum": "arbitrum-one",
        "polygon": "polygon-pos",
        "bsc": "binance-smart-chain",
        "avalanche": "avalanche",
    }
    for chain, contracts in contract_addresses_by_chain.items():
        if not contracts:
            continue
        joined = ",".join(addr.lower() for addr in contracts)
        platform = platform_map.get(chain, chain)
        url = (
            f"{COINGECKO_API}/{platform}?contract_addresses={joined}"
            "&vs_currencies=usd"
        )
        try:
            resp = requests.get(url, headers=headers)
            data = resp.json()
            if isinstance(data, dict):
                for addr in contracts:
                    info = data.get(addr.lower())
                    prices[addr.lower()] = info.get("usd", 0) if info else 0
            else:
                print(
                    f"[!] Réponse inattendue de CoinGecko pour {chain}: {data}"
                )
        except Exception as exc:  # pragma: no cover - network failure
            print(f"[!] Erreur récupération prix pour {chain}: {exc}")
    return prices


def compute_balances(transactions):
    """Aggregate token balances from normalized transactions."""
    balances = defaultdict(float)
    for tx in transactions:
        key = (tx["chain"], tx["contractAddress"], tx["tokenSymbol"])
        if tx["direction"] == "IN":
            balances[key] += tx["value"]
        else:
            balances[key] -= tx["value"]
    return balances


def main():
    """Collect transactions, compute balances and export CSV summaries."""
    all_transactions = []
    contract_addresses_by_chain = defaultdict(set)

    for chain in CHAIN_IDS:
        print(f"[*] Chargement {chain}...")
        txs = fetch_erc20_transactions(chain, ETH_ADDRESS, ETHERSCAN_API_KEY)
        norm_txs = normalize_transactions(txs, chain)
        all_transactions.extend(norm_txs)
        for tx in norm_txs:
            contract_addresses_by_chain[chain].add(tx["contractAddress"])

    prices = get_token_prices(contract_addresses_by_chain)
    balances = compute_balances(all_transactions)

    filtered_transactions = []
    for tx in all_transactions:
        price_key = tx["contractAddress"].lower()
        usd_price = prices.get(price_key, 0)
        usd_value = tx["value"] * usd_price
        if usd_value >= 1:
            tx_copy = tx.copy()
            tx_copy["usd_price"] = usd_price
            tx_copy["usd_value"] = usd_value
            filtered_transactions.append(tx_copy)

    df_tx = pd.DataFrame(filtered_transactions)
    if not df_tx.empty:
        df_tx.sort_values(by="timestamp", inplace=True)
    df_tx.to_csv("transactions.csv", index=False)

    summary_rows = []
    for (chain, addr, symbol), amount in balances.items():
        usd_price = prices.get(addr.lower(), 0)
        usd_value = amount * usd_price
        if usd_value < 1:
            continue
        summary_rows.append(
            {
                "chain": chain,
                "token": symbol,
                "contract": addr,
                "amount": amount,
                "usd_price": usd_price,
                "usd_value": usd_value,
            }
        )

    df_summary = pd.DataFrame(summary_rows)
    if not df_summary.empty:
        df_summary.sort_values(by="usd_value", ascending=False, inplace=True)
    df_summary.to_csv("token_balances.csv", index=False)

    print("\n[✓] Export EVM terminé : transactions.csv et token_balances.csv")


if __name__ == "__main__":
    main()
