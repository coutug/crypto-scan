import os
import requests
import pandas as pd
from datetime import datetime, timezone
from collections import defaultdict
from dotenv import load_dotenv

# --------- LOAD ENV VARIABLES ---------
load_dotenv()

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")
SOLANA_ADDRESS = os.getenv("SOLANA_ADDRESS")

# Validate required environment variables early to avoid confusing runtime errors
required_vars = {
    "WALLET_ADDRESS": WALLET_ADDRESS,
    "ETHERSCAN_API_KEY": ETHERSCAN_API_KEY,
    "SOLANA_ADDRESS": SOLANA_ADDRESS,
}
missing = [name for name, value in required_vars.items() if not value]
if missing:
    missing_str = ", ".join(missing)
    raise EnvironmentError(f"Missing required environment variables: {missing_str}")

# Mapping chain names to their Etherscan chain IDs
CHAIN_IDS = {
    "ethereum": 1,
    "arbitrum": 42161,
    "polygon": 137,
    "bsc": 56,
    "avalanche": 43114
}

COINGECKO_API = "https://api.coingecko.com/api/v3/simple/token_price"

# --------- FUNCTIONS ---------
def fetch_erc20_transactions(chain: str, address: str, api_key: str):
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
        print(f"[!] Pas de données pour {chain} : {data.get('message')}")
        return []
    return data["result"]

def normalize_transactions(transactions, chain):
    normalized = []
    for tx in transactions:
        value = int(tx['value']) / (10 ** int(tx['tokenDecimal']))
        normalized.append({
            'chain': chain,
            'timeStamp': datetime.fromtimestamp(int(tx['timeStamp']), timezone.utc),
            'hash': tx['hash'],
            'from': tx['from'],
            'to': tx['to'],
            'tokenName': tx['tokenName'],
            'tokenSymbol': tx['tokenSymbol'],
            'contractAddress': tx['contractAddress'].lower(),
            'value': value,
            'direction': 'IN' if tx['to'].lower() == WALLET_ADDRESS.lower() else 'OUT',
        })
    return normalized

def get_token_prices(contract_addresses_by_chain):
    prices = {}
    headers = {
        'accept': 'application/json',
        'x-cg-demo-api-key': COINGECKO_API_KEY
    }
    for chain, contracts in contract_addresses_by_chain.items():
        if not contracts:
            continue
        if chain == 'solana':
            contracts = set(contracts)
            token_contracts = [c for c in contracts if c != 'SOL']
            if token_contracts:
                joined = ','.join(token_contracts)
                url = f"{COINGECKO_API}/solana?contract_addresses={joined}&vs_currencies=usd"
                try:
                    resp = requests.get(url, headers=headers)
                    data = resp.json()
                    if isinstance(data, dict):
                        for addr in token_contracts:
                            info = data.get(addr)
                            prices[addr] = info.get('usd', 0) if info else 0
                    else:
                        print(f"[!] Réponse inattendue de CoinGecko pour solana: {data}")
                except Exception as e:
                    print(f"[!] Erreur récupération prix pour solana tokens: {e}")
            if 'SOL' in contracts:
                try:
                    resp = requests.get(
                        "https://api.coingecko.com/api/v3/simple/price",
                        params={"ids": "solana", "vs_currencies": "usd"},
                        headers=headers,
                    )
                    sol_price = resp.json().get('solana', {}).get('usd', 0)
                    prices['SOL'] = sol_price
                except Exception as e:
                    print(f"[!] Erreur récupération prix pour SOL: {e}")
            continue

        joined = ','.join(addr.lower() for addr in contracts)
        platform_map = {
            'ethereum': 'ethereum',
            'arbitrum': 'arbitrum-one',
            'polygon': 'polygon-pos',
            'bsc': 'binance-smart-chain',
            'avalanche': 'avalanche',
        }
        platform = platform_map.get(chain, chain)
        url = f"{COINGECKO_API}/{platform}?contract_addresses={joined}&vs_currencies=usd"
        try:
            resp = requests.get(url, headers=headers)
            data = resp.json()
            if isinstance(data, dict):
                for addr in contracts:
                    key = addr.lower()
                    info = data.get(key)
                    prices[key] = info.get('usd', 0) if info else 0
            else:
                print(f"[!] Réponse inattendue de CoinGecko pour {chain}: {data}")
        except Exception as e:
            print(f"[!] Erreur récupération prix pour {chain}: {e}")
    return prices

def compute_balances(transactions):
    balances = defaultdict(float)
    for tx in transactions:
        key = (tx['chain'], tx['contractAddress'], tx['tokenSymbol'])
        if tx['direction'] == 'IN':
            balances[key] += tx['value']
        else:
            balances[key] -= tx['value']
    return balances


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
                    "chain": "solana",
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
                    "chain": "solana",
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

# --------- MAIN SCRIPT ---------
all_transactions = []
contract_addresses_by_chain = defaultdict(set)

for chain in CHAIN_IDS:
    print(f"[*] Chargement {chain}...")
    txs = fetch_erc20_transactions(chain, WALLET_ADDRESS, ETHERSCAN_API_KEY)
    norm_txs = normalize_transactions(txs, chain)
    all_transactions.extend(norm_txs)
    for tx in norm_txs:
        contract_addresses_by_chain[chain].add(tx['contractAddress'])

print("[*] Chargement solana...")
sol_txs = fetch_solana_transactions(SOLANA_ADDRESS)
all_transactions.extend(sol_txs)
for tx in sol_txs:
    contract_addresses_by_chain['solana'].add(tx['contractAddress'])
sol_balances = fetch_solana_balances(SOLANA_ADDRESS)
for (mint, _symbol), _amount in sol_balances.items():
    contract_addresses_by_chain['solana'].add(mint)

prices = get_token_prices(contract_addresses_by_chain)
balances = compute_balances(all_transactions)
for (mint, symbol), amount in sol_balances.items():
    balances[('solana', mint, symbol)] = amount

# Export des transactions complètes
df_tx = pd.DataFrame(all_transactions)
df_tx.sort_values(by='timeStamp', inplace=True)
df_tx.to_csv("transactions_all_chains.csv", index=False)

# Export du résumé des soldes
summary_rows = []
for (chain, addr, symbol), amount in balances.items():
    price_key = addr.lower() if chain != 'solana' else addr
    usd_price = prices.get(price_key, 0)
    summary_rows.append({
        'chain': chain,
        'token': symbol,
        'contract': addr,
        'amount': amount,
        'usd_price': usd_price,
        'usd_value': amount * usd_price
    })

df_summary = pd.DataFrame(summary_rows)
df_summary.sort_values(by='usd_value', ascending=False, inplace=True)
df_summary.to_csv("token_balances_summary.csv", index=False)

print("\n[✓] Export terminé : transactions_all_chains.csv et token_balances_summary.csv")
