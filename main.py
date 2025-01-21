import json

import example_utils

from hyperliquid.utils import constants

USDC_SYMBOL_SPOT = "USDC"
HYPE_SYMBOL_PERP = "HYPE"
HYPE_SYMBOL_SPOT = HYPE_SYMBOL_PERP + "/" + USDC_SYMBOL_SPOT
SLIPPAGE = 0.02
decimals = 0
BUFFER_MULTIPLIER = 1

def round(num, decimals):
    return float(int(num * 10 ** decimals) / 10 ** decimals)

def get_decimals(info, symbol):
    if "USDC" in symbol:
        raise Exception("Must get_decimals with perp symbol")
    meta = info.meta()
    for coin in meta['universe']:
        if coin['name'] == symbol:
            return coin['szDecimals']
        
    raise Exception(f"Coin {symbol} not found in meta")

def process_result(result):
    if result["status"] == "ok":
        for status in result["response"]["data"]["statuses"]:
            try:
                filled = status["filled"]
            except KeyError:
                print(status)
                raise(f'Error: {status["error"]}')
    else:
        raise Exception(f'Error: Request to HyperLiquid failed')
    return result

# Open a short position
def open_short(exchange, symbol, size):
    size = round(size,decimals)
    print(f"Opening short position with size {size}")
    order_result = exchange.market_open(symbol, False, size, slippage=SLIPPAGE)
    return(process_result(order_result))

# Close a short position
def close_short(exchange, symbol):
    order_result = exchange.market_close(symbol, slippage=SLIPPAGE)
    return(process_result(order_result))

# Swap token/USDC
def swap_token_usdc(exchange, symbol, size_usdc):
    size_usdc = round(size_usdc, decimals)
    print(f"Swapping {size_usdc} spot tokens for USDC...")
    order_result = exchange.market_open(symbol, False, size_usdc) 
    return(process_result(order_result))

# Swap USDC/token
def swap_usdc_token(exchange, symbol, size_token):
    size_token = round(size_token, decimals)
    print(f"Swapping USDC for {size_token} spot tokens...")
    order_result = exchange.market_open(symbol, True, size_token) 
    return(process_result(order_result))

# Find total spot balance
def find_spot_total(info, address, coin_name):
    for balance in info.spot_user_state(address)['balances']:
        if balance['coin'] == coin_name:
            return float(balance['total'])
    return 0.0

# Find max leverage for a coin
def get_max_leverage(info, coin_name):
    meta = info.meta()
    for coin in meta['universe']:
        if coin['name'] == coin_name:
            return coin['maxLeverage']
    raise Exception(f"Coin {coin_name} not found in meta")

# Get price of a symbol
def get_price(info, symbol):
    l2_data = info.l2_snapshot(symbol)
    first_bid = float(l2_data['levels'][0][0]['px'])
    first_ask = float(l2_data['levels'][1][0]['px']) 
    return (first_bid + first_ask) / 2

# Get a list of all open positions (perps)
def get_positions(info, address):
    user_state = info.user_state(address)
    positions = []
    for position in user_state["assetPositions"]:
        positions.append(position["position"])
    if len(positions) > 0:
        return positions
    else:
        return []

def calculate_position_balance(x_0, y_0, p, M, L):
    """
    Calculates the necessary change in spot tokens or USDC to balance the position
    x = USDC
    y = spot tokens
    x_0 = initial USDC
    y_0 = initial spot tokens
    p = price of spot tokens (note here we assume the price to be equal to the short perp price)
    M = margin multiplier to add buffer to the position
    L = leverage of the short perp position

    The number of spot tokens X amount of USDC can cover = L * X / p * M

    So L * X / p * M must be equal to y_0

    x = x+0 + delta_x
    y = y_0 + delta_y

    delta_x = -delta_y * p
    delta_y = -delta_x / p

    and this formula is derived to solve for delta_y

    delta_y = (L * x_0)/(p * (M + L)) - (M * y_0) / (M + L)
    """
    delta_y = (L * x_0)/(p * (M + L)) - (M * y_0) / (M + L)
    delta_x = -delta_y * p
    return delta_x, delta_y

def print_account_state(spot_balance, spot_USDC_balance, perps_USDC_balance):
    print(f"Spot USDC balance:\t{spot_USDC_balance}")
    print(f"Spot token balance:\t{spot_balance}")
    print(f"Perps USDC balance:\t{perps_USDC_balance}")

def main():
    print()
    print("setting up connection with HyperLiquid...")
    address, info, exchange = example_utils.setup(base_url=constants.MAINNET_API_URL, skip_ws=True)

    decimals = get_decimals(info, HYPE_SYMBOL_PERP)

    print()
    print("fetching spot balances...")
    # Get the current spot balance
    spot_balance = find_spot_total(info, address, HYPE_SYMBOL_SPOT)
    spot_USDC_balance = find_spot_total(info, address, USDC_SYMBOL_SPOT)
    
    if(spot_USDC_balance < 10):
        print(f"NOTE: You have {spot_USDC_balance} USDC in your account. For it to be utilized in this strategy USDC must be in the spot account")
        print("The USDC will have some portion swapped to spot token and the other transferred to perps for use as collateral")

    # Get the current USDC perps balance
    # withdrawable is the amount of USDC that can be withdrawn, and seems to best reflect the max amount that can be used to open a perp position
    print()
    print("fetching perps balances...")
    perps_USDC_balance = info.user_state(address)['withdrawable']

    print()
    print("STARTING ACCOUNT STATE")
    print_account_state(spot_balance, spot_USDC_balance, perps_USDC_balance)
    
    print()
    print("Calculating position...")
    (usdc_change, spot_change) = calculate_position_balance(spot_USDC_balance, spot_balance, get_price(info, HYPE_SYMBOL_SPOT), BUFFER_MULTIPLIER, get_max_leverage(info, HYPE_SYMBOL_PERP))

    print("expected perp input value: ", spot_change + spot_balance)
    print()
    print(f"USDC change: {usdc_change}")
    print(f"Spot change: {spot_change}")
    print("Confirm? (y/n)")
    confirm = input()
    if(confirm != "y"):
        print("Exiting...")
        exit()
    
    # swap from spot to USDC
    if(usdc_change > 0):
        # assert that the spot change is negative
        assert(spot_change < 0, "ERROR: spot and USDC change cannot be positive at the same time")  

        result = swap_token_usdc(exchange, HYPE_SYMBOL_SPOT, usdc_change)
        print(result)
    # swap from USDC to spot
    elif(spot_change > 0):
        # assert that the USDC change is negative
        assert(usdc_change < 0, "ERROR: spot and USDC change cannot be negative at the same time")
        
        result = swap_usdc_token(exchange, HYPE_SYMBOL_SPOT, spot_change)
        print(result)
    else:
        print("No change in position")
    
    print()
    perps_USDC_balance = info.user_state(address)['withdrawable']
    print(f"moving {perps_USDC_balance} USDC to perps account...")

    current_usdc_balance = spot_USDC_balance + usdc_change
    result = exchange.usd_class_transfer(current_usdc_balance, True)
    print(result)
    
    print()
    print("placing short perp position...")
    current_spot_balance = spot_change + spot_balance
    result = open_short(exchange, HYPE_SYMBOL_PERP, current_spot_balance)
    print(result)

if __name__ == "__main__":
    main()
