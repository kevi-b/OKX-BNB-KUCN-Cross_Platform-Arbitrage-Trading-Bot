import requests
import json
import time
import asyncio
import os
from dotenv import load_dotenv
from kucoin.client import Market as KucoinMarket
from kucoin.client import Trade as KucoinTrade
from kucoin.client import User as KucoinUser
from binance.client import Client as BinanceClient, AsyncClient as BinanceAsyncClient
from okx.client import Client as OKXClient, AsyncClient as OKXAsyncClient

load_dotenv()

api_key_kucoin = os.getenv("KUCOIN_API_KEY")
api_secret_kucoin = os.getenv("KUCOIN_API_SECRET")
api_passphrase_kucoin = os.getenv("KUCOIN_API_PASSPHRASE")

api_key_binance = os.getenv("BINANCE_API_KEY")
api_secret_binance = os.getenv("BINANCE_API_SECRET")

api_key_okx = os.getenv("OKX_API_KEY")
api_secret_okx = os.getenv("OKX_API_SECRET")
okx_passphrase = os.getenv("OKX_PASSPHRASE")

kucoin_client = KucoinTrade(api_key_kucoin, api_secret_kucoin, api_passphrase_kucoin, is_sandbox=False, url='')
kucoin_user = KucoinUser(api_key_kucoin, api_secret_kucoin, api_passphrase_kucoin)
binance_client = BinanceClient(api_key_binance, api_secret_binance)
okx_client = OKXClient(api_key_okx, api_secret_okx, okx_passphrase, test=True)

binance_async_client = BinanceAsyncClient(api_key_binance, api_secret_binance)
okx_async_client = OKXAsyncClient(api_key_okx, api_secret_okx, okx_passphrase, test=True)

amount_dict = {"USDT": 0, "BTC": 0, "ETH": 0, "BNB": 0, "XRP": 0} 

symbol_mapping = {
    "BTC-USDT": {"Kucoin": "BTC-USDT", "Binance": "BTCUSDT", "OKX": "BTC-USDT-SWAP"},
    "ETH-USDT": {"Kucoin": "ETH-USDT", "Binance": "ETHUSDT", "OKX": "ETH-USDT-SWAP"},
    "BNB-USDT": {"Kucoin": "BNB-USDT", "Binance": "BNBUSDT", "OKX": "BNB-USDT-SWAP"},
    "XRP-USDT": {"Kucoin": "XRP-USDT", "Binance": "XRPUSDT", "OKX": "XRP-USDT-SWAP"}, 
}

min_profit_margin = 0.01 
max_trade_size_btc = 0.001  
order_book_depth = 50  
stop_loss_percentage = 0.005  
profit_threshold = 0.003  
order_timeout_seconds = 10  

kucoin_fee_rate = 0.001  
binance_fee_rate = 0.001  
okx_fee_rate = 0.001  

api_call_timestamps = {
    "Kucoin": [],
    "Binance": [],
    "OKX": []
}
rate_limit_windows = {
    "Kucoin": 60, 
    "Binance": 60,  
    "OKX": 10      
}
max_calls_per_window = {
    "Kucoin": 100,  
    "Binance": 1200, 
    "OKX": 20      
}

def update_balances():
    global amount_dict
    try:
        for currency in amount_dict:
            account_info = kucoin_user.get_account_list(currency=currency)
            if account_info:
                amount_dict[currency] = float(account_info[0]['available'])
            else:
                print(f"Warning: Currency {currency} not found on Kucoin.")
    except Exception as e:
        print(f"Error updating balances: {e}")

update_balances()
print("Initial Balances:", amount_dict)

kucoin_market_data = KucoinMarket()
kucoin_inc_list = {}
kucoin_qinc_list = {}

for x in kucoin_market_data.get_symbol_list():
    kucoin_inc_list[x['symbol']] = x['baseIncrement']
    kucoin_qinc_list[x['symbol']] = x['quoteIncrement']

def get_coin_arbitrage(url):
    try:
        response = requests.get(url).json()
        return response
    except Exception as e:
        print(f"Error fetching arbitrage data: {e}")
        return None

def collect_tradeables(json_obj):
    coin_list = []
    for coin in json_obj['data']['ticker']:
        if coin['symbol'] in symbol_mapping:
            coin_list.append(coin['symbol'])
    return coin_list

def structure_triangular_pairs(coin_list):
    triangular_pairs_list = []
    remove_duplicates_list = []
    pairs_list = coin_list[0:]

    for pair_a in pairs_list:
        pair_a_split = pair_a.split('-')
        a_base = pair_a_split[0]
        a_quote = pair_a_split[1]

        a_pair_box = [a_base, a_quote]

        for pair_b in pairs_list:
            pair_b_split = pair_b.split('-')
            b_base = pair_b_split[0]
            b_quote = pair_b_split[1]

            if pair_b != pair_a:
                if b_base in a_pair_box or b_quote in a_pair_box:
                    for pair_c in pairs_list:
                        pair_c_split = pair_c.split('-')
                        c_base = pair_c_split[0]
                        c_quote = pair_c_split[1]

                        if pair_c != pair_a and pair_c != pair_b:
                            combine_all = [pair_a, pair_b, pair_c]
                            pair_box = [a_base, a_quote, b_base, b_quote, c_base, c_quote]

                            counts_c_base = pair_box.count(c_base)
                            counts_c_quote = pair_box.count(c_quote)

                            if counts_c_base == 2 and counts_c_quote == 2 and c_base != c_quote:
                                combined = pair_a + ',' + pair_b + ',' + pair_c
                                unique_item = ''.join(sorted(combine_all))
                                if unique_item not in remove_duplicates_list:
                                    match_dict = {
                                        "a_base": a_base,
                                        "b_base": b_base,
                                        "c_base": c_base,
                                        "a_quote": a_quote,
                                        "b_quote": b_quote,
                                        "c_quote": c_quote,
                                        "pair_a": pair_a,
                                        "pair_b": pair_b,
                                        "pair_c": pair_c,
                                        "combined": combined
                                    }
                                    triangular_pairs_list.append(match_dict)
                                    remove_duplicates_list.append(unique_item)
    return triangular_pairs_list

def get_price_for_t_pair(t_pair, prices_json):
    pair_a = t_pair['pair_a']
    pair_b = t_pair['pair_b']
    pair_c = t_pair['pair_c']

    try:
        for x in prices_json['data']['ticker']:
            if x['symbol'] == pair_a:
                pair_a_ask = float(x['sell'])
                pair_a_bid = float(x['buy'])
            if x['symbol'] == pair_b:
                pair_b_ask = float(x['sell'])
                pair_b_bid = float(x['buy'])
            if x['symbol'] == pair_c:
                pair_c_ask = float(x['sell'])
                pair_c_bid = float(x['buy'])

        return {
            "pair_a_ask": pair_a_ask,
            "pair_a_bid": pair_a_bid,
            "pair_b_ask": pair_b_ask,
            "pair_b_bid": pair_b_bid,
            "pair_c_ask": pair_c_ask,
            "pair_c_bid": pair_c_bid
        }

    except Exception as e:
        print(f"Error getting prices for triangular pair: {e}")
        return None

def cal_triangular_arb_surface_rate(t_pair, prices_dict):
    starting_amount = 1
    min_surface_rate = 0
    surface_dict = {}

    a_base = t_pair['a_base']
    a_quote = t_pair['a_quote']
    b_base = t_pair['b_base']
    b_quote = t_pair['b_quote']
    c_base = t_pair['c_base']
    c_quote = t_pair['c_quote']
    pair_a = t_pair['pair_a']
    pair_b = t_pair['pair_b']
    pair_c = t_pair['pair_c']

    if prices_dict is None:
        print("Error: prices_dict is None. Skipping calculation.")
        return surface_dict

    a_ask = prices_dict['pair_a_ask']
    a_bid = prices_dict['pair_a_bid']
    b_ask = prices_dict['pair_b_ask']
    b_bid = prices_dict['pair_b_bid']
    c_ask = prices_dict['pair_c_ask']
    c_bid = prices_dict['pair_c_bid']

    direction_list = ['forward', 'reverse']
    for direction in direction_list:
        calculated = 0

        swap_1 = 0
        swap_2 = 0
        swap_3 = 0
        swap_1_rate = 0
        swap_2_rate = 0
        swap_3_rate = 0

        if direction == "forward":
            swap_1 = a_base
            swap_2 = a_quote
            swap_1_rate = (1 / a_ask) * (1 - kucoin_fee_rate) if a_ask != 0 else 0
            direction_trade_1 = "base_to_quote"
            acquired_coin_t1 = starting_amount * swap_1_rate

            if a_quote == b_quote and calculated == 0:
                swap_2_rate = b_bid * (1 - kucoin_fee_rate)
                acquired_coin_t2 = acquired_coin_t1 * swap_2_rate
                direction_trade_2 = "quote_to_base"
                contract_2 = pair_b

                if b_base == c_base:
                    swap_3 = c_base
                    swap_3_rate = (1 / c_ask) * (1 - kucoin_fee_rate) if c_ask != 0 else 0
                    direction_trade_3 = "base_to_quote"
                    contract_3 = pair_c

                if b_base == c_quote:
                    swap_3 = c_quote
                    swap_3_rate = c_bid * (1 - kucoin_fee_rate)
                    direction_trade_3 = "quote_to_base"
                    contract_3 = pair_c

                acquired_coin_t3 = acquired_coin_t2 * swap_3_rate
                calculated = 1

            if a_quote == b_base and calculated == 0:
                swap_2_rate = (1 / b_ask) * (1 - binance_fee_rate) if b_ask != 0 else 0
                acquired_coin_t2 = acquired_coin_t1 * swap_2_rate
                direction_trade_2 = "base_to_quote"
                contract_2 = pair_b

                if b_quote == c_base:
                    swap_3 = c_base
                    swap_3_rate = (1 / c_ask) * (1 - okx_fee_rate) if c_ask != 0 else 0
                    direction_trade_3 = "base_to_quote"
                    contract_3 = pair_c

                if b_quote == c_quote:
                    swap_3 = c_quote
                    swap_3_rate = c_bid * (1 - okx_fee_rate)
                    direction_trade_3 = "quote_to_base"
                    contract_3 = pair_c

                acquired_coin_t3 = acquired_coin_t2 * swap_3_rate
                calculated = 1

            if a_quote == c_quote and calculated == 0:
                swap_2_rate = c_bid * (1 - okx_fee_rate)
                acquired_coin_t2 = acquired_coin_t1 * swap_2_rate
                direction_trade_2 = "quote_to_base"
                contract_2 = pair_c

                if c_base == b_base:
                    swap_3 = b_base
                    swap_3_rate = (1 / b_ask) * (1 - binance_fee_rate) if b_ask != 0 else 0
                    direction_trade_3 = "base_to_quote"
                    contract_3 = pair_b

                if c_base == b_quote:
                    swap_3 = b_quote
                    swap_3_rate = b_bid * (1 - binance_fee_rate)
                    direction_trade_3 = "quote_to_base"
                    contract_3 = pair_b

                acquired_coin_t3 = acquired_coin_t2 * swap_3_rate
                calculated = 1

            if a_quote == c_base and calculated == 0:
                swap_2_rate = (1 / c_ask) * (1 - okx_fee_rate) if c_ask != 0 else 0
                acquired_coin_t2 = acquired_coin_t1 * swap_2_rate
                direction_trade_2 = "base_to_quote"
                contract_2 = pair_c

                if c_quote == b_base:
                    swap_3 = b_base
                    swap_3_rate = (1 / b_ask) * (1 - binance_fee_rate) if b_ask != 0 else 0
                    direction_trade_3 = "base_to_quote"
                    contract_3 = pair_b

                if c_quote == b_quote:
                    swap_3 = b_quote
                    swap_3_rate = b_bid * (1 - binance_fee_rate)
                    direction_trade_3 = "quote_to_base"
                    contract_3 = pair_b

                acquired_coin_t3 = acquired_coin_t2 * swap_3_rate
                calculated = 1

        if direction == "reverse":
            swap_1 = a_quote
            swap_2 = a_base
            swap_1_rate = a_bid * (1 - kucoin_fee_rate)
            direction_trade_1 = "quote_to_base"
            acquired_coin_t1 = starting_amount * swap_1_rate

            if a_base == b_quote and calculated == 0:
                swap_2_rate = b_bid * (1 - kucoin_fee_rate)
                acquired_coin_t2 = acquired_coin_t1 * swap_2_rate
                direction_trade_2 = "quote_to_base"
                contract_2 = pair_b

                if b_base == c_base:
                    swap_3 = c_base
                    swap_3_rate = (1 / c_ask) * (1 - kucoin_fee_rate) if c_ask != 0 else 0
                    direction_trade_3 = "base_to_quote"
                    contract_3 = pair_c

                if b_base == c_quote:
                    swap_3 = c_quote
                    swap_3_rate = c_bid * (1 - kucoin_fee_rate)
                    direction_trade_3 = "quote_to_base"
                    contract_3 = pair_c

                acquired_coin_t3 = acquired_coin_t2 * swap_3_rate
                calculated = 1

            if a_base == b_base and calculated == 0:
                swap_2_rate = (1 / b_ask) * (1 - binance_fee_rate) if b_ask != 0 else 0
                acquired_coin_t2 = acquired_coin_t1 * swap_2_rate
                direction_trade_2 = "base_to_quote"
                contract_2 = pair_b

                if b_quote == c_base:
                    swap_3 = c_base
                    swap_3_rate = (1 / c_ask) * (1 - okx_fee_rate) if c_ask != 0 else 0
                    direction_trade_3 = "base_to_quote"
                    contract_3 = pair_c

                if b_quote == c_quote:
                    swap_3 = c_quote
                    swap_3_rate = c_bid * (1 - okx_fee_rate)
                    direction_trade_3 = "quote_to_base"
                    contract_3 = pair_c

                acquired_coin_t3 = acquired_coin_t2 * swap_3_rate
                calculated = 1

            if a_base == c_quote and calculated == 0:
                swap_2_rate = c_bid * (1 - okx_fee_rate)
                acquired_coin_t2 = acquired_coin_t1 * swap_2_rate
                direction_trade_2 = "quote_to_base"
                contract_2 = pair_c

                if c_base == b_base:
                    swap_3 = b_base
                    swap_3_rate = (1 / b_ask) * (1 - binance_fee_rate) if b_ask != 0 else 0
                    direction_trade_3 = "base_to_quote"
                    contract_3 = pair_b

                if c_base == b_quote:
                    swap_3 = b_quote
                    swap_3_rate = b_bid * (1 - binance_fee_rate)
                    direction_trade_3 = "quote_to_base"
                    contract_3 = pair_b

                acquired_coin_t3 = acquired_coin_t2 * swap_3_rate
                calculated = 1

            if a_base == c_base and calculated == 0:
                swap_2_rate = (1 / c_ask) * (1 - okx_fee_rate) if c_ask != 0 else 0
                acquired_coin_t2 = acquired_coin_t1 * swap_2_rate
                direction_trade_2 = "base_to_quote"
                contract_2 = pair_c

                if c_quote == b_base:
                    swap_3 = b_base
                    swap_3_rate = (1 / b_ask) * (1 - binance_fee_rate) if b_ask != 0 else 0
                    direction_trade_3 = "base_to_quote"
                    contract_3 = pair_b

                if c_quote == b_quote:
                    swap_3 = b_quote
                    swap_3_rate = b_bid * (1 - binance_fee_rate)
                    direction_trade_3 = "quote_to_base"
                    contract_3 = pair_b

                acquired_coin_t3 = acquired_coin_t2 * swap_3_rate
                calculated = 1

        profit_loss = acquired_coin_t3 - starting_amount
        profit_loss_perc = (profit_loss / starting_amount) * 100 if profit_loss != 0 else 0

        if profit_loss_perc > min_surface_rate:
            surface_dict = {
                "swap_1": swap_1,
                "swap_2": swap_2,
                "swap_3": swap_3,
                "contract_1": contract_1,
                "contract_2": contract_2,
                "contract_3": contract_3,
                "direction_trade_1": direction_trade_1,
                "direction_trade_2": direction_trade_2,
                "direction_trade_3": direction_trade_3,
                "starting_amount": starting_amount,
                "acquired_coin_t1": acquired_coin_t1,
                "acquired_coin_t2": acquired_coin_t2,
                "acquired_coin_t3": acquired_coin_t3,
                "swap_1_rate": swap_1_rate,
                "swap_2_rate": swap_2_rate,
                "swap_3_rate": swap_3_rate,
                "profit_loss": profit_loss,
                "profit_loss_perc": profit_loss_perc,
                "direction": direction,
            }

            return surface_dict

    return surface_dict

async def get_kucoin_orderbook_async(symbol, depth):
    await handle_rate_limits("Kucoin")

    try:
        return kucoin_market_data.get_part_order(symbol, depth)
    except Exception as e:
        print(f"Error fetching Kucoin order book for {symbol}: {e}")
        return None

async def get_binance_orderbook_async(symbol, depth):
    await handle_rate_limits("Binance")

    try:
        return await binance_async_client.get_order_book(symbol=symbol, limit=depth)
    except Exception as e:
        print(f"Error fetching Binance order book for {symbol}: {e}")
        return None

async def get_okx_orderbook_async(instId, depth):
    await handle_rate_limits("OKX")

    try:
        response = await okx_async_client.get(f'/api/v5/market/books?instId={instId}&sz={depth}')
        return response.data[0] 
    except Exception as e:
        print(f"Error fetching OKX order book for {instId}: {e}")
        return None

def simulate_fills(orderbook, direction, amount, slippage_tolerance=0.001):
    if orderbook is None:
        print("Error: Order book is None. Cannot simulate fills.")
        return 0, 0

    filled_amount = 0
    total_cost = 0
    remaining_amount = amount

    if direction == 'buy':
        levels = orderbook['asks']
    else:  # direction == 'sell'
        levels = orderbook['bids']

    for level in levels:
        price = float(level[0])
        quantity = float(level[1])

        if direction == 'buy':
            price *= (1 + slippage_tolerance)
        else:
            price *= (1 - slippage_tolerance)

        if remaining_amount <= quantity:
            filled_amount += remaining_amount
            total_cost += remaining_amount * price
            remaining_amount = 0
            break
        else:
            filled_amount += quantity
            total_cost += quantity * price
            remaining_amount -= quantity

    effective_price = total_cost / filled_amount if filled_amount > 0 else 0
    return filled_amount, effective_price

async def execute_kucoin_trade(symbol, side, size=None, funds=None, stop_price=None):
    try:
        if side == 'buy':
            order = kucoin_client.create_limit_order(symbol, side, stop_price, size)
        else: 
            order = kucoin_client.create_limit_order(symbol, side, stop_price, size)
        order_id = order['orderId']
        print(f"Executed {side} order on Kucoin for {symbol}: {size if size else funds}")

        await handle_order_timeout("Kucoin", symbol, order_id)

        return order_id
    except Exception as e:
        print(f"Error executing Kucoin trade: {e}")
        return None

async def execute_binance_trade(symbol, side, quantity, stop_price=None):
    try:
        if side == 'buy':
            order = binance_client.order_limit_buy(symbol=symbol, quantity=quantity, price=stop_price)
        else: 
            order = binance_client.order_limit_sell(symbol=symbol, quantity=quantity, price=stop_price)
        order_id = order['orderId']
        print(f"Executed {side} order on Binance for {symbol}: {quantity}")

        await handle_order_timeout("Binance", symbol, order_id) 

        return order_id
    except Exception as e:
        print(f"Error executing Binance trade: {e}")
        return None

async def execute_okx_trade(symbol, side, size, stop_price=None):
    try:
        order = okx_client.create_order(
            instId=symbol,
            tdMode='cash',
            side=side,
            ordType='limit',
            sz=str(size),
            px=str(stop_price)
        )
        order_id = order['data'][0]['ordId']
        print(f"Executed {side} order on OKX for {symbol}: {size}")

        await handle_order_timeout("OKX", symbol, order_id)

        if stop_price:
            if side == 'buy':
                stop_side = 'sell'
            else:
                stop_side = 'buy'
            okx_client.create_order(
                instId=symbol,
                tdMode='cash',
                side=stop_side,
                ordType='stop_loss', 
                sz=str(size),
                slTriggerPx=str(stop_price)  
            )
            print(f"Placed {stop_side} stop-loss order at {stop_price} on OKX for {symbol}")

        return order_id
    except Exception as e:
        print(f"Error executing OKX trade: {e}")
        return None

async def find_arbitrage_opportunities():
    global structured_pairs
    while True:
        prices = get_coin_arbitrage('https://api.kucoin.com/api/v1/market/allTickers')

        arbitrage_opportunity = None

        if prices is not None:
            for t_pair in structured_pairs:
                prices_dict = get_price_for_t_pair(t_pair, prices)
                if prices_dict is not None:
                    surface_arb = cal_triangular_arb_surface_rate(t_pair, prices_dict)
                    if surface_arb and surface_arb.get('profit_loss_perc', 0) > profit_threshold:
                        real_rate_arb = get_depth_from_orderbook(surface_arb)
                        if real_rate_arb and real_rate_arb.get('real_rate_perc', 0) > profit_threshold:
                            arbitrage_opportunity = real_rate_arb
                            break

        if arbitrage_opportunity:
            await execute_arbitrage(arbitrage_opportunity)

        await asyncio.sleep(0.1) 

async def execute_arbitrage(real_rate_arb):
    global amount_dict

    contract_1 = real_rate_arb['contract_1']
    contract_2 = real_rate_arb['contract_2']
    contract_3 = real_rate_arb['contract_3']

    exchange_1 = "Kucoin"
    symbol_1 = symbol_mapping[contract_1]["Kucoin"]
    direction_1 = real_rate_arb['contract_1_direction']

    if contract_2 in symbol_mapping:
        if symbol_mapping[contract_2]["Binance"]:
            exchange_2 = "Binance"
            symbol_2 = symbol_mapping[contract_2]["Binance"]
        elif symbol_mapping[contract_2]["OKX"]:
            exchange_2 = "OKX"
            symbol_2 = symbol_mapping[contract_2]["OKX"]

    direction_2 = real_rate_arb['contract_2_direction']

    if contract_3 in symbol_mapping:
        if symbol_mapping[contract_3]["Binance"]:
            exchange_3 = "Binance"
            symbol_3 = symbol_mapping[contract_3]["Binance"]
        elif symbol_mapping[contract_3]["OKX"]:
            exchange_3 = "OKX"
            symbol_3 = symbol_mapping[contract_3]["OKX"]

    direction_3 = real_rate_arb['contract_3_direction']

    swap_1 = real_rate_arb['swap_1']
    first_amount1 = amount_dict.get(swap_1)

    if not all([swap_1, symbol_1, direction_1, first_amount1]):
        print("Error: Missing required keys in real_rate_arb or insufficient funds. Skipping arbitrage.")
        return

    if first_amount1 > max_trade_size_btc:
        first_amount1 = max_trade_size_btc

    kucoin_orderbook = await get_kucoin_orderbook_async(symbol_1, order_book_depth)
    filled_amount1, effective_price1 = simulate_fills(kucoin_orderbook, direction_1,
                                                      float(first_amount1))

    if filled_amount1 > 0:
        if direction_1 == 'buy':
            stop_price1 = effective_price1 * (1 - stop_loss_percentage)
        else:
            stop_price1 = effective_price1 * (1 + stop_loss_percentage)

        order_id1 = await execute_kucoin_trade(symbol_1, direction_1,
                                               size=filled_amount1, stop_price=stop_price1)

        if order_id1 is None:
            print("Error: Trade 1 failed. Exiting arbitrage sequence.")
            return

        await asyncio.sleep(0.5)

        update_balances()

        if exchange_2 == "Binance":
            execute_trade_2 = execute_binance_trade
            orderbook_2 = await get_binance_orderbook_async(symbol_2, order_book_depth)
        elif exchange_2 == "OKX":
            execute_trade_2 = execute_okx_trade
            orderbook_2 = await get_okx_orderbook_async(symbol_2, order_book_depth)

        filled_amount2, effective_price2 = simulate_fills(orderbook_2, direction_2, float(amount_dict[swap_2]))
        if direction_2 == 'buy':
            stop_price2 = effective_price2 * (1 - stop_loss_percentage)
        else:
            stop_price2 = effective_price2 * (1 + stop_loss_percentage)

        order_id2 = await execute_trade_2(symbol_2, direction_2,
                                          size=filled_amount2, stop_price=stop_price2)

        if order_id2 is None:
            print("Error: Trade 2 failed. Exiting arbitrage sequence.")
            return

        await asyncio.sleep(0.5)

        update_balances()

        if exchange_3 == "Binance":
            execute_trade_3 = execute_binance_trade
            orderbook_3 = await get_binance_orderbook_async(symbol_3, order_book_depth)
        elif exchange_3 == "OKX":
            execute_trade_3 = execute_okx_trade
            orderbook_3 = await get_okx_orderbook_async(symbol_3, order_book_depth)

        filled_amount3, effective_price3 = simulate_fills(orderbook_3, direction_3, float(amount_dict[swap_1]))
        if direction_3 == 'buy':
            stop_price3 = effective_price3 * (1 - stop_loss_percentage)
        else:
            stop_price3 = effective_price3 * (1 + stop_loss_percentage)

        order_id3 = await execute_trade_3(symbol_3, direction_3,
                                          size=filled_amount3, stop_price=stop_price3)

        if order_id3 is None:
            print("Error: Trade 3 failed. Exiting arbitrage sequence.")
            return

        update_balances()
        print("Balances after trades:", amount_dict)
    else:
        print("Trade 1 not filled. Skipping arbitrage.")


async def handle_order_timeout(exchange, symbol, order_id):
    start_time = time.time()
    while True:
        if exchange == "Kucoin":
            order_status = kucoin_client.get_order_details(order_id)
            if order_status['status'] == 'done':
                break
        elif exchange == "Binance":
            order_status = binance_client.get_order(symbol=symbol, orderId=order_id)
            if order_status['status'] == 'FILLED':
                break
        elif exchange == "OKX":
            order_status = okx_client.get_order_details(instId=symbol, ordId=order_id)
            if order_status['data'][0]['state'] == 'filled':
                break

        if time.time() - start_time > order_timeout_seconds:
            if exchange == "Kucoin":
                kucoin_client.cancel_order(order_id)
            elif exchange == "Binance":
                binance_client.cancel_order(symbol=symbol, orderId=order_id)
            elif exchange == "OKX":
                okx_client.cancel_order(instId=symbol, ordId=order_id)
            print(f"{exchange} order {order_id} timed out and was canceled.")
            return False 
        await asyncio.sleep(1)
    return True  

async def handle_rate_limits(exchange):