import os
import requests
import pandas as pd
from datetime import datetime, timezone
from collections import defaultdict
from dotenv import load_dotenv

# --------- LOAD ENV VARIABLES ---------
load_dotenv()

SOLANA_ADDRESS = os.getenv("SOLANA_ADDRESS")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

required_vars = {
    "SOLANA_ADDRESS": SOLANA_ADDRESS,
    "COINGECKO_API_KEY": COINGECKO_API_KEY,
}
missing = [name for name, value in required_vars.items() if not value]
if missing:
    missing_str = ", ".join(missing)
    raise EnvironmentError(f"Missing required environment variables: {missing_str}")

COINGECKO_API = "https://api.coingecko.com/api/v3/simple/token_price"

# --------- SOLANA FUNCTIONS ---------
def fetch_solana_transactions(address: str, limit: int = 100):
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
            "method": "getTransaction",
            "params": [
                signature,
                {
                    "encoding": "jsonParsed",
                    "maxSupportedTransactionVersion": 0,
                },
            ],
        }
        resp = requests.post(url, json=payload, headers=headers)
        result = resp.json().get("result")
        if not result:
            continue
        block_time = result.get("blockTime")
        meta = result.get("meta", {})

        # -- SPL token deltas --
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
                    "timeStamp": datetime.fromtimestamp(block_time, timezone.utc)
                    if block_time
                    else None,
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

        # -- Native SOL delta --
        message = result.get("transaction", {}).get("message", {})
        account_keys = [k.get("pubkey") for k in message.get("accountKeys", [])]
        pre_sol = meta.get("preBalances", [])
        post_sol = meta.get("postBalances", [])
        for idx, pubkey in enumerate(account_keys):
            if pubkey != address:
                continue
            before = pre_sol[idx] / 1e9 if idx < len(pre_sol) else 0
            after = post_sol[idx] / 1e9 if idx < len(post_sol) else 0
            delta = after - before
            if delta == 0:
                continue
            direction = "IN" if delta > 0 else "OUT"
            transactions.append(
                {
                    "timeStamp": datetime.fromtimestamp(block_time, timezone.utc)
                    if block_time
                    else None,
                    "hash": signature,
                    "from": address if direction == "OUT" else "",
                    "to": address if direction == "IN" else "",
                    "tokenName": "SOL",
                    "tokenSymbol": "SOL",
                    "contractAddress": "SOL",
                    "value": abs(delta),
                    "direction": direction,
                }
            )
    return transactions


def fetch_solana_balances(address: str):
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

    # native SOL balance
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "getBalance",
        "params": [address],
    }
    resp = requests.post(url, json=payload, headers=headers)
    lamports = resp.json().get("result", {}).get("value", 0)
    balances[("SOL", "SOL")] = lamports / 1e9
    return balances


def get_solana_token_prices(contracts):
    prices = {}
    headers = {
        "accept": "application/json",
        "x-cg-demo-api-key": COINGECKO_API_KEY,
    }
    contracts = set(contracts)
    token_contracts = [c for c in contracts if c != "SOL"]
    if token_contracts:
        joined = ",".join(token_contracts)
        url = f"{COINGECKO_API}/solana?contract_addresses={joined}&vs_currencies=usd"
        try:
            resp = requests.get(url, headers=headers)
            data = resp.json()
            if isinstance(data, dict):
                for addr in token_contracts:
                    info = data.get(addr)
                    prices[addr] = info.get("usd", 0) if info else 0
            else:
                print(f"[!] Réponse inattendue de CoinGecko pour solana: {data}")
        except Exception as e:
            print(f"[!] Erreur récupération prix pour solana tokens: {e}")
    if "SOL" in contracts:
        try:
            resp = requests.get(
                "https://api.coingecko.com/api/v3/simple/price",
                params={"ids": "solana", "vs_currencies": "usd"},
                headers=headers,
            )
            sol_price = resp.json().get("solana", {}).get("usd", 0)
            prices["SOL"] = sol_price
        except Exception as e:
            print(f"[!] Erreur récupération prix pour SOL: {e}")
    return prices


def compute_balances(transactions):
    balances = defaultdict(float)
    for tx in transactions:
        key = (tx["contractAddress"], tx["tokenSymbol"])
        if tx["direction"] == "IN":
            balances[key] += tx["value"]
        else:
            balances[key] -= tx["value"]
    return balances


if __name__ == "__main__":
    print("[*] Chargement solana...")
    sol_txs = fetch_solana_transactions(SOLANA_ADDRESS)
    contract_addresses = {tx["contractAddress"] for tx in sol_txs}
    sol_balances = fetch_solana_balances(SOLANA_ADDRESS)
    for (mint, _symbol) in sol_balances.keys():
        contract_addresses.add(mint)

    prices = get_solana_token_prices(contract_addresses)
    balances = compute_balances(sol_txs)
    for (mint, symbol), amount in sol_balances.items():
        balances[(mint, symbol)] = amount

    df_tx = pd.DataFrame(sol_txs)
    df_tx.sort_values(by="timeStamp", inplace=True)
    df_tx.to_csv("solana_transactions.csv", index=False)

    summary_rows = []
    for (addr, symbol), amount in balances.items():
        usd_price = prices.get(addr, 0)
        summary_rows.append(
            {
                "token": symbol,
                "contract": addr,
                "amount": amount,
                "usd_price": usd_price,
                "usd_value": amount * usd_price,
            }
        )

    df_summary = pd.DataFrame(summary_rows)
    df_summary.sort_values(by="usd_value", ascending=False, inplace=True)
    df_summary.to_csv("solana_token_balances_summary.csv", index=False)

    print(
        "\n[✓] Export solana terminé : solana_transactions.csv et solana_token_balances_summary.csv"
    )
