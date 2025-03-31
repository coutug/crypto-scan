import os
import requests
import pandas as pd
from dotenv import load_dotenv
from datetime import datetime, timezone
from collections import defaultdict

# --------- CONFIGURATION ---------
load_dotenv()

WALLET_ADDRESS = os.getenv("WALLET_ADDRESS")
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY")
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY")

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
        'x-cg-pro-api-key': COINGECKO_API_KEY
    }
    for chain, contracts in contract_addresses_by_chain.items():
        if not contracts:
            continue
        joined = ','.join(contracts)
        platform = 'ethereum' if chain == 'ethereum' else chain
        url = f"{COINGECKO_API}/{platform}?contract_addresses={joined}&vs_currencies=usd"
        try:
            resp = requests.get(url, headers=headers)
            data = resp.json()
            if isinstance(data, dict):
                for addr in contracts:
                    info = data.get(addr.lower())
                    if info and 'usd' in info:
                        prices[addr.lower()] = info['usd']
                    else:
                        prices[addr.lower()] = 0
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

prices = get_token_prices(contract_addresses_by_chain)
balances = compute_balances(all_transactions)

# Export des transactions complètes
df_tx = pd.DataFrame(all_transactions)
df_tx.sort_values(by='timeStamp', inplace=True)
df_tx.to_csv("transactions_all_chains.csv", index=False)

# Export du résumé des soldes
summary_rows = []
for (chain, addr, symbol), amount in balances.items():
    usd_price = prices.get(addr, 0)
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