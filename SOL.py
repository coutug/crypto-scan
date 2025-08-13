"""Export SPL token transfers for the Solana chain only.

The script mirrors ``main.py`` but focuses solely on Solana. It gathers
transactions and balances, retrieves USD prices from CoinGecko and
writes ``transactions.csv`` and ``token_balances.csv``.
"""

import os
from collections import defaultdict
from datetime import datetime, timezone

import pandas as pd
import requests
from dotenv import load_dotenv

# --------- LOAD ENV VARIABLES ---------
load_dotenv()

SOL_ADDRESS = os.getenv("SOL_ADDRESS")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

required_vars = {
    "SOL_ADDRESS": SOL_ADDRESS,
    "COINGECKO_API_KEY": COINGECKO_API_KEY,
}
missing = [name for name, value in required_vars.items() if not value]
if missing:
    missing_str = ", ".join(missing)
    raise EnvironmentError(
        f"Missing required environment variables: {missing_str}"
    )

COINGECKO_API = "https://api.coingecko.com/api/v3/simple/token_price"


def fetch_solana_transactions(address: str, limit: int = 100):
    """Retrieve SPL token movements for a Solana ``address``."""
    url = "https://api.mainnet-beta.solana.com"
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getSignaturesForAddress",
        "params": [address, {"limit": limit}],
    }
    resp = requests.post(url, json=payload, headers=headers)
    signatures = resp.json().get("result", [])
    transactions = []
    for sig in signatures:
        signature = sig["signature"]
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getParsedTransaction",
            "params": [signature, "jsonParsed"],
        }
        resp = requests.post(url, json=payload, headers=headers)
        result = resp.json().get("result")
        if not result:
            continue
        block_time = result.get("blockTime")
        meta = result.get("meta", {})
        pre_bal = {
            b["mint"]: float(b["uiTokenAmount"].get("uiAmount", 0))
            for b in meta.get("preTokenBalances", [])
            if b.get("owner") == address
        }
        post_bal = {
            b["mint"]: float(b["uiTokenAmount"].get("uiAmount", 0))
            for b in meta.get("postTokenBalances", [])
            if b.get("owner") == address
        }
        for mint in set(pre_bal) | set(post_bal):
            before = pre_bal.get(mint, 0)
            after = post_bal.get(mint, 0)
            delta = after - before
            if delta == 0:
                continue
            direction = "IN" if delta > 0 else "OUT"
            transactions.append(
                {
                    "chain": "solana",
                    "timestamp": (
                        datetime.fromtimestamp(block_time, timezone.utc)
                        if block_time
                        else None
                    ),
                    "hash": signature,
                    "from": address if direction == "OUT" else "",
                    "to": address if direction == "IN" else "",
                    "tokenName": mint,
                    "tokenSymbol": mint,
                    "contractAddress": mint,
                    "value": abs(delta),
                    "direction": direction,
                }
            )
    return transactions


def fetch_solana_balances(address: str):
    """Return current SPL token balances for a Solana ``address``."""
    url = "https://api.mainnet-beta.solana.com"
    headers = {"Content-Type": "application/json"}
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getTokenAccountsByOwner",
        "params": [
            address,
            {"programId": "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"},
            {"encoding": "jsonParsed"},
        ],
    }
    resp = requests.post(url, json=payload, headers=headers)
    result = resp.json().get("result", {}).get("value", [])
    balances = {}
    for entry in result:
        info = entry["account"]["data"]["parsed"]["info"]
        mint = info["mint"]
        amount = float(info["tokenAmount"].get("uiAmount", 0))
        balances[(mint, mint)] = amount
    return balances


def get_token_prices(contract_addresses_by_chain):
    """Fetch USD prices for Solana tokens."""
    prices = {}
    headers = {
        "accept": "application/json",
        "x-cg-demo-api-key": COINGECKO_API_KEY,
    }
    contracts = contract_addresses_by_chain.get("solana", set())
    if not contracts:
        return prices
    joined = ",".join(contracts)
    url = (
        f"{COINGECKO_API}/solana?contract_addresses={joined}"
        "&vs_currencies=usd"
    )
    try:
        resp = requests.get(url, headers=headers)
        data = resp.json()
        if isinstance(data, dict):
            for addr in contracts:
                info = data.get(addr)
                prices[addr] = info.get("usd", 0) if info else 0
        else:
            print(f"[!] Réponse inattendue de CoinGecko pour solana: {data}")
    except Exception as exc:  # pragma: no cover - network failure
        print(f"[!] Erreur récupération prix pour solana: {exc}")
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

    print("[*] Chargement solana...")
    sol_txs = fetch_solana_transactions(SOL_ADDRESS)
    all_transactions.extend(sol_txs)
    for tx in sol_txs:
        contract_addresses_by_chain["solana"].add(tx["contractAddress"])
    sol_balances = fetch_solana_balances(SOL_ADDRESS)
    for mint, _ in sol_balances.items():
        contract_addresses_by_chain["solana"].add(mint)

    prices = get_token_prices(contract_addresses_by_chain)
    balances = compute_balances(all_transactions)
    for (mint, symbol), amount in sol_balances.items():
        balances[("solana", mint, symbol)] = amount

    filtered_transactions = []
    for tx in all_transactions:
        price_key = tx["contractAddress"]
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
        usd_price = prices.get(addr, 0)
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

    print("\n[✓] Export Solana terminé : "
          "transactions.csv et token_balances.csv")


if __name__ == "__main__":
    main()
