# Objectif
Ce projet vise à centraliser l’historique de toutes vos transactions
crypto afin de simplifier la comptabilité et le calcul de l’impôt à la
fin de l’année.
Le script Python récupère les transferts ERC‑20 depuis plusieurs chaînes
EVM, calcule les soldes token par token à l’aide des prix CoinGecko et
exporte le tout sous forme de fichiers CSV lisibles dans LibreOffice
Calc (ou tout tableur similaire).

## Fonctionnement actuel
Chaînes EVM prises en charge : Ethereum, Arbitrum, Polygon, BSC,
Avalanche.

Autre chaîne à prendre en charge: Solana

### Structure
Le repo est formé d'un script appelé main.py.

2 nouveaux fichiers de tests devraient être créés:
- EVM.py
- SOL.py

Ces 2 fichiers devraient tester les portions du script en lien avec les chaînes mentionnés dans leur titre afin de pouvoir debugger plus facilement les parties du script.

## Entrées nécessaires
ETH_ADDRESS – adresse publique du portefeuille à analyser

SOL_ADDRESS – adresse publique du portefeuille à analyser

ETHERSCAN_API_KEY – clé d’API (compatible Etherscan et dérivés)

COINGECKO_API_KEY – clé d’API pour les prix des tokens

## Sorties générées

transactions.csv – historique détaillé des transferts

token_balances.csv – soldes agrégés et valorisation USD

## Extensions en cours
Ajout du support Solana: extraction via des appels à https://api.mainnet-beta.solana.com

## Conventions de contribution
Python ≥ 3.10

Respecter le style PEP 8 et privilégier un code clair et commenté.

Ajouter tout nouveau module Python dans requirements.txt avec une
version minimale compatible.

Pour chaque nouvelle chaîne EVM, compléter le dictionnaire CHAIN_IDS
et adapter les fonctions de récupération si nécessaire.