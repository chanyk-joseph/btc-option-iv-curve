import asyncio
import json
import numpy as np
import matplotlib.pyplot as plt

from jsonrpcclient import Ok, parse_json, request_json
import websockets

# Get the client ID and secret on: My Account -> API -> API Access -> ADD NEW KEY
# see: https://docs.deribit.com/#public-auth
client_id='xxxxxx'
client_secret='4JfX8AxxxxxxxxxxxxxxxxxxxxxxxxxxxxxcOuY'
currency = 'BTC'
option_date_str = '24JUN22'

async def init_connection(client_id, client_secret):
    ws = await websockets.connect('wss://www.deribit.com/ws/api/v2')

    credential = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret
    }
    await ws.send(request_json('public/auth', params=credential))
    response = parse_json(await ws.recv())
    if isinstance(response, Ok):
        print('Login Successful! Token: \n%s\n' % response.result)
    else:
        raise RuntimeError('Failed to Init Connection: %s' % response.message)
    return ws

async def get_active_instruments(ws, currency, kind, name_filter):
    params = {
        "currency": currency,
        "kind": kind,
        "expired": False
    }
    await ws.send(request_json('public/get_instruments', params))
    response = parse_json(await ws.recv())
    if isinstance(response, Ok):
        instruments = list(filter(lambda obj: name_filter in obj['instrument_name'], response.result))
        instrument_names = list(map(lambda obj: obj['instrument_name'], instruments))
        print('Retrieved Instruments: \n%s\n' % (', '.join(instrument_names)))
        return instruments
    else:
        raise RuntimeError('Failed to get instruments list of %s %s: \n%s' % (currency, kind, response.message))

async def instruments_data_retriever(ws, instrument_names, datastore):
    params = {
        "channels": list(map(lambda str: 'incremental_ticker.%s' % str, instrument_names))
    }
    await ws.send(request_json("private/subscribe", params))
    # Sample Response:
    # {
    #     "jsonrpc": "2.0",
    #     "method": "subscription",
    #     "params": {
    #         "channel": "incremental_ticker.BTC-24JUN22-31000-C",
    #         "data": {
    #             "underlying_price": 30007.22,
    #             "timestamp": 1654804786505,
    #             "max_price": 0.0775,
    #             "instrument_name": "BTC-24JUN22-31000-C",
    #             "index_price": 29993.81,
    #             "greeks": {
    #                 "vega": 23.42994,
    #                 "theta": -51.80833,
    #                 "rho": 4.61846,
    #                 "delta": 0.42436
    #             },
    #             "estimated_delivery_price": 29993.81,
    #             "bid_iv": 63.58,
    #             "best_bid_amount": 44.0,
    #             "ask_iv": 65.5
    #         }
    #     }
    # }
    while True:
        response_str = await ws.recv()
        tick = json.loads(response_str)

        if 'params' in tick and 'data' in tick['params']:
            tick_data = tick['params']['data']
            instrument_name = tick_data['instrument_name']
            tmp = instrument_name.split('-')
            strike_price_str = tmp[2]

            if 'ask_iv' not in tick_data or 'bid_iv' not in tick_data:
                continue
            if int(tick_data['ask_iv']) == 0 or int(tick_data['bid_iv']) == 0:
                continue

            if tmp[3] == 'C':
                datastore['calls'][strike_price_str] = tick_data
            elif tmp[3] == 'P':
                datastore['puts'][strike_price_str] = tick_data

def pretty_print_datastore(datastore):
    def print_table(option_type, data):
        strike_prices = sorted(data.keys(), key=lambda strike_str: int(strike_str))
        print("{:<15} {:<10} {:<10}".format(('%s Strike' % option_type), 'Bid IV', 'Ask IV'))
        for strike in strike_prices:
            print ("{:<15} {:<10} {:<10}".format(strike, data[strike]['bid_iv'], data[strike]['ask_iv']))
        print()
    
    print_table('Call', datastore['calls'])
    print_table('Put', datastore['puts'])

async def refresh_plot_and_equation(datastore, plot_title, refresh_interval_seconds):
    def get_strikes_and_iv(datastore, option_type, iv_type):
        strike_prices_str = sorted(datastore[option_type].keys(), key=lambda strike_str: int(strike_str))
        strikes = list(map(lambda str: int(str), strike_prices_str))
        ivs = list(map(lambda strike_str: datastore[option_type][strike_str][iv_type], strike_prices_str))
        return (strikes, ivs)

    plt.ion()
    fig, axs = plt.subplots(2, 2, figsize=(15,15))
    ((ax1, ax2), (ax3, ax4)) = axs
    fig.suptitle(plot_title)

    def plot(ax, title, strikes, ivs, color):
        model = np.poly1d(np.polyfit(strikes, ivs, 2))
        quadratic_equation = str(model)
        polyline = np.linspace(strikes[0]-1000, strikes[len(strikes)-1]+1000, 500)

        ax.clear()
        ax.set_title(title)
        ax.scatter(strikes, ivs)
        ax.plot(polyline, model(polyline), color)
        ax.set(xlabel='Strikes', ylabel='Implied volatility (%)')
        ax.label_outer()
        
        print('%s: \n%s\n' % (title, quadratic_equation))


    while True:
        await asyncio.sleep(refresh_interval_seconds)
        if len(datastore['calls']) == 0 or len(datastore['puts']) == 0:
            print('Waiting for data...')
            continue

        print('\n\n\n========================================================================')
        pretty_print_datastore(datastore)

        # Examples
        # strikes_c = [25000, 26000, 28000, 29000, 30000, 31000, 32000, 33000, 34000, 35000, 36000, 38000, 40000, 42000, 44000, 45000, 46000]
        # bid_ivs_c = [50.57, 58.75, 67.59, 65.76, 64.4, 63.22, 61.59, 61.31, 61.14, 62.47, 63.46, 67.0, 72.01, 77.28, 78.88, 82.88, 86.77]
        strikes_c, bid_ivs_c = get_strikes_and_iv(datastore, option_type='calls', iv_type='bid_iv')
        _, ask_ivs_c = get_strikes_and_iv(datastore, option_type='calls', iv_type='ask_iv')
        strikes_p, bid_ivs_p = get_strikes_and_iv(datastore, option_type='puts', iv_type='bid_iv')
        _, ask_ivs_p = get_strikes_and_iv(datastore, option_type='puts', iv_type='ask_iv')

        plot(ax1, 'Call Bid IV', strikes_c, bid_ivs_c, 'tab:blue')
        plot(ax2, 'Call Ask IV', strikes_c, ask_ivs_c, 'tab:orange')
        plot(ax3, 'Put Bid IV', strikes_p, bid_ivs_p, 'tab:green')
        plot(ax4, 'Put Ask IV', strikes_p, ask_ivs_p, 'tab:red')
        plt.draw()
        plt.pause(0.1)

async def main():
    ws = await init_connection(client_id, client_secret)
    instruments = await get_active_instruments(ws, currency, kind='option', name_filter=option_date_str)

    datastore = {
        "calls": {
            # ...
            # "30000": {
            #     "bid_iv": 64.81,
            #     "ask_iv": 66.71
            # }
            # "31000": {
            #      ...
            # }
            # ...
        },
        "puts": {}
    }
    instrument_names = list(map(lambda obj: obj['instrument_name'], instruments))
    await asyncio.gather(instruments_data_retriever(ws, instrument_names, datastore), refresh_plot_and_equation(datastore, plot_title=('%s @ %s' % (currency, option_date_str)),refresh_interval_seconds=1))

asyncio.run(main())