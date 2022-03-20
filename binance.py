"""
随着数据中心的投入使用
API的封装越来越没有必要
因为封装的原因是之前数据不互通，同一个API需要调用多次
现在封装的倾向要向着通用化转变
例如只封装需要多次调用的websocket连接、request这类
"""

import json
import hmac
import time
import traceback
from typing import Union, Dict, List, Callable
import requests
import math
import threading
from hashlib import sha256
import websockets
import asyncio
import functools

"""
此脚本用于放置对币安API的封装
"""

base_url = 'binance.com'  # 基本网址，用于快速切换国内地址和国际地址，国际地址是binance.com
only_print_error = True  # 是否仅仅打印错误请求，开启后只会打印出错误请求，但不会影响追踪文件写入
trace_to_file = False  # 是否将追踪请求写入到文件
print_simple_trace = True  # 开启后只会在控制台显示精简请求，但是错误请求会永远显示完整版
proxy_url = None  # 不为None则使用该地址转发代理


class BinanceException(Exception):

    def __init__(self, status_code, response):
        """
        币安的请求没有返回200就抛出此异常
        """
        super(BinanceException, self).__init__(status_code, response)
        self.status_code = status_code
        self.response = response


class CantRetryException(Exception):
    def __init__(self, status_code, response):
        """
        经过一定程度的判断，无法简单retry解决就返回此异常
        """
        super(CantRetryException, self).__init__(status_code, response)
        self.status_code = status_code
        self.response = response


def get_timestamp():
    """
    获取币安常用的毫秒级timestamp
    """
    return str(round(time.time() * 1000))


def float_to_str_floor(amount: float, precision: int = 8) -> str:
    """
    将float转为指定精度的str格式，一般用于对高精度计算结果下单，会向下取整避免多下\n
    如不指定精度，则默认为币安最大精度8\n
    对于str格式，会自动转为float再进行精度转换
    """
    if isinstance(amount, str):
        amount = float(amount)
    res = str(math.floor(amount * (10 ** precision)) / (10 ** precision))
    # 如果最后结尾是.0，则把.0消除
    if res[-2:] == '.0':
        res = res[:-2]
    return res


def float_to_str_ceil(amount: float, precision: int = 8) -> str:
    """
    将float转为指定精度的str格式，一般用于对高精度计算结果下单，会向上取整避免少下\n
    如不指定精度，则默认币安最大精度8
    """
    if isinstance(amount, str):
        amount = float(amount)
    res = str(math.ceil(amount * (10 ** precision)) / (10 ** precision))
    # 如果最后结尾是.0，则把.0消除
    if res[-2:] == '.0':
        res = res[:-2]
    return res


def float_to_str_round(amount: float, precision: int = 8) -> str:
    """
    将float转为指定精度的str格式，一般用于消除0.000000000001和0.9999999999\n
    会对指定精度四舍五入，如不指定精度，则默认币安最大精度8
    """
    if isinstance(amount, str):
        amount = float(amount)
    res = str(round(amount * (10 ** precision)) / (10 ** precision))
    # 如果最后结尾是.0，则把.0消除
    if res[-2:] == '.0':
        res = res[:-2]
    return res


def make_query_string(**kwargs) -> str:
    """
    这个函数会接收任意个参数，并返回对应的GET STRING
    :return: 返回格式为aaa=xxx&bbb=xxx&ccc=xxx

    """
    res = ''
    if len(kwargs.keys()) != 0:
        pass
    else:
        return ''
    for key in kwargs.keys():
        res += key + '=' + str(kwargs[key]) + '&'
    res = res[:len(res) - 1]  # 删掉最后多余的&
    return res


class Client(object):
    def __init__(self):
        # 读取配置文件
        with open('config.json', 'r', encoding='utf-8') as f:
            jsons = json.loads(f.read())

            self.public_key = jsons['binance_public_key']
            self.private_key = jsons['binance_private_key']

        # 创建一个共用session
        self.session = requests.Session()

    async def request(self, area_url: str, path_url, method: str, data: dict, test=False, send_signature=True,
                      retry_count: int = 3, retry_interval: int = 0, auto_timestamp: bool = False) -> Dict:
        """
        用于向币安发送请求的内部API\n
        如果请求状态码不是200，会引发BinanceException\n
        默认会将返回结果解析为json\n
        :param area_url: 头部的地址，例如api、fapi、dapi
        :param path_url: 路径地址，例如/fapi/v2/account
        :param method: 请求方法，仅限POST、GET、PUT
        :param data: 发送的数据，dict会自动转换成http参数，str则不转换
        :param test: 是否添加/test路径，用于测试下单，默认False
        :param send_signature: 是否发送签名，有的api不接受多余的参数，就不能默认发送签名
        :param retry_count: 返回状态码不为200时，自动重试的次数
        :param retry_interval: 自动尝试的间隔(秒)
        :param auto_timestamp: 是否自动添加timestamp并且在重试时自动更新timestamp
        :return: 返回的数据文本格式
        """
        while True:
            method = method.upper()
            if method != 'POST' and method != 'GET' and method != 'PUT':
                raise Exception('请求方法必须为POST、GET、PUT，大小写不限')
            headers = {
                'X-MBX-APIKEY': self.public_key
            }
            if test:
                test_path = '/test'
            else:
                test_path = ''
            if isinstance(data, dict):
                # 如果启用了auto_timestamp，则忽略掉用户传入的timestamp，并且重新生成一个新的
                if auto_timestamp:
                    data['timestamp'] = get_timestamp()
                str_data = make_query_string(**data)

            elif isinstance(data, str):
                str_data = data
            else:
                raise Exception('data格式错误，必须为dict，或者使用make_query_string转换后的str')
            signature = hmac.new(self.private_key.encode('ascii'),
                                 str_data.encode('ascii'), digestmod=sha256).hexdigest()
            if send_signature:
                url = 'https://{}.{}{}{}?{}&signature={}'.format(
                    area_url, base_url, path_url, test_path, str_data, signature)
            else:
                url = 'https://{}.{}{}{}?{}'.format(
                    area_url, base_url, path_url, test_path, str_data)

            if method == 'GET':
                func = self.session.get
            elif method == 'POST':
                func = self.session.post
            else:
                func = self.session.put

            if proxy_url is None:
                proxies = None
            else:
                proxies = {
                    'http': proxy_url,
                    'https': proxy_url
                }

            r: requests.Response = await asyncio.get_running_loop(). \
                run_in_executor(None, functools.partial(func, url, headers=headers, proxies=proxies))

            if not only_print_error:
                if print_simple_trace:
                    print('-----start-----')
                    print('URL:', url)
                    print('STATUS CODE:', r.status_code)
                    print('TEXT:', r.text[:50])
                    print('-----ended-----')
                else:
                    print('-----start-----')
                    print('URL:', url)
                    print('STATUS CODE:', r.status_code)
                    print('TEXT:', r.text)
                    print('-----ended-----')
            if trace_to_file:
                with open('requests_trace.txt', 'a+', encoding='utf-8') as f:
                    f.writelines([
                        '-----start-----\n',
                        'URL: {}\n'.format(url),
                        'STATUS CODE: {}\n'.format(r.status_code),
                        'TEXT: {}\n'.format(r.text),
                        '-----ended-----\n'
                    ])
            if r.status_code != 200:
                if only_print_error:
                    print('-----start-----')
                    print('URL:', url)
                    print('STATUS CODE:', r.status_code)
                    print('TEXT:', r.text)
                    print('-----ended-----')
                if retry_count > 0:
                    retry_count -= 1
                else:
                    raise BinanceException(r.status_code, r.text)
            else:
                return r.json()

            # 等待一定时间之后再重试
            await asyncio.sleep(retry_interval)

    async def create_listen_key(self, mode: str, symbol: str = None) -> str:
        """
        创建一个listen_key用来订阅账户的websocket信息
        :param mode: MAIN、MARGIN、ISOLATED、FUTURE，代表现货、全仓、逐仓、期货
        :param symbol: 仅逐仓需要传入，代表哪个逐仓
        :return: 返回的listen_key
        """
        if mode != 'MAIN' and mode != 'FUTURE' and mode != 'MARGIN' and mode != 'ISOLATED':
            raise Exception('mode必须为MAIN、MARGIN、ISOLATED、FUTURE')
        if mode == 'MAIN':
            res = await self.request('api', '/api/v3/userDataStream', 'POST', {}, send_signature=False)
            res = res['listenKey']
            return res
        elif mode == 'MARGIN':
            res = await self.request('api', '/sapi/v1/userDataStream', 'POST', {}, send_signature=False)
            res = res['listenKey']
            return res
        elif mode == 'ISOLATED':
            if symbol is None:
                raise Exception('需要传入逐仓的symbol')
            symbol = symbol.upper()
            res = await self.request('api', '/sapi/v1/userDataStream/isolated', 'POST', {
                'symbol': symbol
            }, send_signature=False)
            res = res['listenKey']
            return res
        else:
            res = await self.request('fapi', '/fapi/v1/listenKey', 'POST', {}, send_signature=False)
            res = res['listenKey']
            return res

    async def overtime_listen_key(self, mode: str, key: str, symbol: str = None):
        """
        延长一个listen_key的有效时间\n
        根据官网的说明，默认有效时间是60分钟，推荐30分钟延长一次\n
        :param mode: MAIN、r，代表现货或者期货
        :param key: 要延长的listen_key
        :param symbol: 仅逐仓需要传入，代表哪个逐仓
        """
        if mode != 'MAIN' and mode != 'FUTURE' and mode != 'MARGIN' and mode != 'ISOLATED':
            raise Exception('mode必须为MAIN、MARGIN、ISOLATED、FUTURE')
        elif mode == 'MAIN':
            await self.request('api', '/api/v3/userDataStream', 'PUT', {
                'listenKey': key
            }, send_signature=False)
        elif mode == 'MARGIN':
            await self.request('api', '/sapi/v1/userDataStream', 'PUT', {
                'listenKey': key
            }, send_signature=False)
        elif mode == 'ISOLATED':
            if symbol is None:
                raise Exception('需要传入逐仓的symbol')
            symbol = symbol.upper()
            await self.request('api', '/sapi/v1/userDataStream/isolated', 'PUT', {
                'listenKey': key,
                'symbol': symbol
            }, send_signature=False)
        else:
            await self.request('fapi', '/fapi/v1/listenKey', 'PUT', data={
                'listenKey': key
            }, send_signature=False)

    async def get_symbol_precision(self, symbol: str, mode: str = None) -> int:
        """
        获取交易对的报价精度，用于按照数量下单时，得知最大货币下单精度\n
        如果不传入mode，则会自动比较期货和现货，传回一个最低精度，用于双向开仓\n
        :param symbol: 要查询的交易对名字
        :param mode: 要查询的模式，仅可查询MAIN，FUTURE。代表现货和期货
        :return: 查询的小数位数量
        """
        # 转换符号到大写
        symbol = symbol.upper()
        if mode is not None:
            mode = mode.upper()

        # 判断mode有没有输入正确
        if mode != 'MAIN' and mode != 'FUTURE' and mode is not None:
            raise Exception('mode输入错误，仅可输入MAIN或者FUTURE')

        # 根据mode获取对应的交易对精度
        if mode == 'MAIN':
            # 获取每个 现货 交易对的规则（下单精度）
            info = await self.request('api', '/api/v3/exchangeInfo', 'GET', {}, send_signature=False)
            info = info['symbols']
            # 在获取的结果里面找到需要的精度信息
            for e in info:
                # 找到对应交易对
                if e['symbol'] == symbol:
                    # 根据asset返回对应的精度
                    return int(e['baseAssetPrecision'])
            else:
                raise Exception('没有找到欲查询的精度信息')
        if mode == 'FUTURE':
            info = await self.request('fapi', '/fapi/v1/exchangeInfo', 'GET', {}, send_signature=False)
            info = info['symbols']
            for e in info:
                if e['symbol'] == symbol:
                    return int(e['quantityPrecision'])
            else:
                raise Exception('没有找到欲查询的精度信息')
        if mode is None:
            main_precision = await self.get_symbol_precision(symbol, 'MAIN')
            future_precision = await self.get_symbol_precision(symbol, 'FUTURE')
            return min(main_precision, future_precision)

    async def trade_market(self, symbol: str, mode: str, amount: Union[str, float, int], side: str, test=False,
                           volume_mode=False) -> Dict:
        """
        下市价单\n
        需要注意的是，amount可以传入float和str\n
        传入str会直接使用此str的数字进行下单\n
        传入float会自动获取要下单货币对的精度，并向下取整转为str再下单\n
        以成交额方式交易可能会有误差导致下单失败，建议确保有足够资产才使用成交额方式下单\n
        期货以成交额模式下单，会自动计算市值并下单\n
        :param symbol: 要下单的交易对符号，会自动转大写
        :param mode: 要下单的模式，可为MAIN(现货)、FUTURE(期货)、MARGIN(全仓杠杆)、ISOLATED(逐仓杠杆)
        :param amount: 要下单的货币数量，默认是货币数量，如果开启成交额模式，则为成交额
        :param side: 下单方向，字符串格式，只能为SELL或者BUY
        :param test: 是否为测试下单，默认False。测试下单不会提交到撮合引擎，用于测试
        :param volume_mode: 是否用成交额模式下单，默认False，开启后amount代表成交额而不是货币数量
        :return: 下单请求提交后，币安返回的结果
        """
        # 转化字符串
        symbol = symbol.upper()
        mode = mode.upper()
        side = side.upper()

        # 判断mode是否填写正确
        if mode != 'MAIN' and mode != 'FUTURE' and mode != 'MARGIN' and mode != 'ISOLATED':
            raise Exception('交易mode填写错误，只能为MAIN FUTURE MARGIN ISOLATED')

        # 判断side是否填写正确
        if side != 'BUY' and side != 'SELL':
            raise Exception('交易side填写错误，只能为SELL或者BUY')

        # 如果期货用了成交额模式，则获取币价来计算下单货币数
        if mode == 'FUTURE' and volume_mode:
            # 获取期货币价最新价格
            latest_price = await self.get_latest_price(symbol, 'FUTURE')
            # 一个除法计算要买多少币
            amount = float(amount) / latest_price

        # 如果amount是float格式则根据精度转换一下
        if isinstance(amount, float):
            # 以币数量下单则获取精度转换，成交额下单则直接转为最高精度
            if not volume_mode:
                if mode == 'MAIN':
                    precision = await self.get_symbol_precision(symbol, 'MAIN')
                else:
                    precision = await self.get_symbol_precision(symbol, 'FUTURE')
                amount = float_to_str_floor(amount, precision)
            else:
                amount = float_to_str_floor(amount)
        elif isinstance(amount, int):
            amount = str(amount)
        elif isinstance(amount, str):
            pass
        else:
            raise Exception('传入amount类型不可识别', type(amount))

        data = {
            'symbol': symbol,
            'side': side,
            'type': 'MARKET',
            'timestamp': get_timestamp()
        }
        # 使用交易额参数下单(非期货)
        if volume_mode and mode != 'FUTURE':
            data['quoteOrderQty'] = amount
        # 使用货币数下单
        else:
            data['quantity'] = amount
        # 加入全仓或者逐仓参数
        if mode == 'MARGIN':
            data['isIsolated'] = 'FALSE'
        if mode == 'ISOLATED':
            data['isIsolated'] = 'TRUE'

        # 根据期货现货不同，发出不同的请求
        if mode == 'MAIN':
            r = await self.request('api', '/api/v3/order', 'POST', data, test=test)
        elif mode == 'FUTURE':
            r = await self.request('fapi', '/fapi/v1/order', 'POST', data, test=test)
        else:
            r = await self.request('api', '/sapi/v1/margin/order', 'POST', data, test=test)

        return r

    async def get_borrowed_asset_amount(self, mode: str) -> dict:
        """
        获取某个模式下的已借入的货币数量\n
        key为货币符号，值为借入数量
        如果是逐仓，key为交易对，内容为dict，有base_asset和quote_asset两个float资产数\n
        以及base_symbol和quote_asset两个资产符号\n
        :param mode: 只能为MARGIN、ISOLATED，代表全仓逐仓
        """
        if mode != 'MARGIN' and mode != 'ISOLATED':
            raise Exception('mode只能为MARGIN、ISOLATED')
        # 根据mode调用不同API查询
        asset_dict = {}
        if mode == 'MARGIN':
            # 获取当前所有的全仓资产
            res = await self.request('api', '/sapi/v1/margin/account', 'GET', {
                'timestamp': get_timestamp()
            })
            res = res['userAssets']
            # 遍历将非零借贷塞入字典
            for e in res:
                if float(e['borrowed']) != 0:
                    asset_dict[e['asset']] = float(e['borrowed'])
        elif mode == 'ISOLATED':
            # 获取当前所有的逐仓资产
            res = await self.request('api', '/sapi/v1/margin/isolated/account', 'GET', {
                'timestamp': get_timestamp()
            })
            res = res['assets']
            # 遍历将非零资产塞入字典
            for e in res:
                if float(e['baseAsset']['borrowed']) != 0 or float(e['quoteAsset']['borrowed']) != 0:
                    asset_dict[e['symbol']] = {}
                    asset_dict[e['symbol']]['base_asset'] = float(e['baseAsset']['borrowed'])
                    asset_dict[e['symbol']]['quote_asset'] = float(e['quoteAsset']['borrowed'])
                    asset_dict[e['symbol']]['base_name'] = e['baseAsset']['asset']
                    asset_dict[e['symbol']]['quote_name'] = e['quoteAsset']['asset']
        else:
            raise Exception('未知的mode', mode)
        return asset_dict

    async def get_all_asset_amount(self, mode: str) -> dict:
        """
        获取某个模式下所有不为0的资产数量\n
        期货使用此函数无法查询仓位，只能查询诸如USDT、BNB之类的资产\n
        如果查询非逐仓，返回的key为资产名字，内容为float的资产数\n
        如果查询逐仓，返回的key为交易对符号，内容为dict，有base_asset和quote_asset两个float资产数\n
        以及base_symbol和quote_asset两个资产符号\n
        :param mode: MAIN、MARGIN、ISOLATED、FUTURE 代表现货、全仓、逐仓、期货
        """
        if mode != 'MAIN' and mode != 'FUTURE' and mode != 'MARGIN' and mode != 'ISOLATED':
            raise Exception('mode只能为MAIN、FUTURE、MARGIN、ISOLATED')

        # 根据mode调用不同API查询
        asset_dict = {}
        if mode == 'MAIN':
            # 获取当前所有现货资产
            res = await self.request('api', '/api/v3/account', 'GET', {
                'timestamp': get_timestamp()
            })
            res = res['balances']
            # 遍历将非零的资产塞入字典
            for e in res:
                if float(e['free']) != 0:
                    asset_dict[e['asset']] = float(e['free'])
        elif mode == 'FUTURE':
            # 获取当前所有期货资产
            res = await self.request('fapi', '/fapi/v2/balance', 'GET', {
                'timestamp': get_timestamp()
            })
            # 遍历将非零资产塞入字典
            for e in res:
                if float(e['maxWithdrawAmount']) != 0:
                    asset_dict[e['asset']] = float(e['maxWithdrawAmount'])
        elif mode == 'MARGIN':
            # 获取当前所有的全仓资产
            res = await self.request('api', '/sapi/v1/margin/account', 'GET', {
                'timestamp': get_timestamp()
            })
            res = res['userAssets']
            # 遍历将非零资产塞入字典
            for e in res:
                if float(e['free']) != 0:
                    asset_dict[e['asset']] = float(e['free'])
        elif mode == 'ISOLATED':
            # 获取当前所有的逐仓资产
            res = await self.request('api', '/sapi/v1/margin/isolated/account', 'GET', {
                'timestamp': get_timestamp()
            })
            res = res['assets']
            # 遍历将非零资产塞入字典
            for e in res:
                if float(e['baseAsset']['free']) != 0 or float(e['quoteAsset']['free']) != 0:
                    asset_dict[e['symbol']] = {}
                    asset_dict[e['symbol']]['base_asset'] = float(e['baseAsset']['free'])
                    asset_dict[e['symbol']]['quote_asset'] = float(e['quoteAsset']['free'])
                    asset_dict[e['symbol']]['base_name'] = e['baseAsset']['asset']
                    asset_dict[e['symbol']]['quote_name'] = e['quoteAsset']['asset']
        else:
            raise Exception('未知的mode', mode)
        return asset_dict

    async def get_asset_amount(self, symbol: str, mode: str) -> float:
        """
        获取可用资产数量，已冻结的资产不会在里面\n
        期货使用此函数无法查询仓位，只能查询诸如USDT、BNB之类的资产\n
        :param symbol: 要查询的资产符号
        :param mode: MAIN、MARGIN、FUTURE 代表现货、全仓、期货
        """
        if symbol is not None:
            symbol = symbol.upper()
        mode = mode.upper()

        if mode != 'MAIN' and mode != 'FUTURE' and mode != 'MARGIN':
            raise Exception('mode只能为MAIN、FUTURE、MARGIN')

        # 根据mode调用不同API查询
        if mode == 'MAIN':
            # 获取当前所有现货资产
            asset_dict = await self.get_all_asset_amount(mode)
            # 查询可用资产数量
            if symbol not in asset_dict.keys():
                return 0
            else:
                return asset_dict[symbol]
        elif mode == 'FUTURE':
            # 获取当前所有期货资产
            asset_dict = await self.get_all_asset_amount(mode)
            # 查询可用资产数量
            if symbol not in asset_dict.keys():
                return 0
            else:
                return asset_dict[symbol]
        elif mode == 'MARGIN':
            # 获取当前所有全仓资产
            asset_dict = await self.get_all_asset_amount(mode)
            # 查询可用资产数量
            if symbol not in asset_dict.keys():
                return 0
            else:
                return asset_dict[symbol]
        else:
            raise Exception('未知的mode', mode)

    async def get_future_position(self, symbol: str = None) -> Union[float, dict]:
        """
        获取期货仓位情况\n
        如果不传入symbol，则返回字典类型的所有仓位，key为大写symbol，且不会返回仓位为0的交易对\n
        :param symbol: 要查询的交易对
        :return: 返回持仓数量，多空使用正负表示
        """
        # 获取当前所有的期货仓位（不是资产）
        res = await self.request('fapi', '/fapi/v2/account', 'GET', {
            'timestamp': get_timestamp()
        })
        res = res['positions']
        if symbol is not None:
            # 有symbol的情况下直接返回symbol的仓位
            for e in res:
                if e['symbol'] == symbol:
                    return float(e['positionAmt'])
            else:
                raise Exception('没有找到查询的交易对仓位')
        else:
            # 没有symbol的情况下返回交易对的仓位字典
            all_price = {}
            for e in res:
                # 过滤掉仓位为0的交易对
                if float(e['positionAmt']) != 0:
                    all_price[e['symbol']] = float(e['positionAmt'])
            return all_price

    async def transfer_asset(self, mode: str, asset_symbol: str, amount: Union[str, float, int]):
        """
        划转指定资产，需要开通万向划转权限\n
        可用的模式如下\n
        MAIN_C2C 现货钱包转向C2C钱包\n
        MAIN_UMFUTURE 现货钱包转向U本位合约钱包\n
        MAIN_CMFUTURE 现货钱包转向币本位合约钱包\n
        MAIN_MARGIN 现货钱包转向杠杆全仓钱包\n
        MAIN_MINING 现货钱包转向矿池钱包\n
        C2C_MAIN C2C钱包转向现货钱包\n
        C2C_UMFUTURE C2C钱包转向U本位合约钱包\n
        C2C_MINING C2C钱包转向矿池钱包\n
        UMFUTURE_MAIN U本位合约钱包转向现货钱包\n
        UMFUTURE_C2C U本位合约钱包转向C2C钱包\n
        UMFUTURE_MARGIN U本位合约钱包转向杠杆全仓钱包\n
        CMFUTURE_MAIN 币本位合约钱包转向现货钱包\n
        MARGIN_MAIN 杠杆全仓钱包转向现货钱包\n
        MARGIN_UMFUTURE 杠杆全仓钱包转向U本位合约钱包\n
        MINING_MAIN 矿池钱包转向现货钱包\n
        MINING_UMFUTURE 矿池钱包转向U本位合约钱包\n
        MINING_C2C 矿池钱包转向C2C钱包\n
        MARGIN_CMFUTURE 杠杆全仓钱包转向币本位合约钱包\n
        CMFUTURE_MARGIN 币本位合约钱包转向杠杆全仓钱包\n
        MARGIN_C2C 杠杆全仓钱包转向C2C钱包\n
        C2C_MARGIN C2C钱包转向杠杆全仓钱包\n
        MARGIN_MINING 杠杆全仓钱包转向矿池钱包\n
        MINING_MARGIN 矿池钱包转向杠杆全仓钱包\n
        :param mode: 划转模式
        :param asset_symbol: 欲划转资产
        :param amount: 划转数目，str格式则直接使用，float则转换为最高精度
        """
        # 将资产和模式转为大写
        mode = mode.upper()
        asset_symbol = asset_symbol.upper()

        if isinstance(amount, float):
            amount = float_to_str_round(amount)
        elif isinstance(amount, int):
            amount = str(amount)
        elif isinstance(amount, str):
            pass
        else:
            raise Exception('传入amount类型不可识别', type(amount))

        await self.request('api', '/sapi/v1/asset/transfer', 'POST', {
            'type': mode,
            'asset': asset_symbol,
            'amount': amount,
            'timestamp': get_timestamp()
        })

    async def get_latest_price(self, symbol: str, mode: str) -> float:
        """
        获取某个货币对的最新价格\n
        :param symbol: 货币对的符号
        :param mode: 查询模式，MAIN或者FUTURE，代表现货或者期货
        """
        symbol = symbol.upper()
        mode = mode.upper()

        # 判断mode是否填写正确
        if mode != 'MAIN' and mode != 'FUTURE':
            raise Exception('交易mode填写错误，只能为MAIN或者FUTURE')

        if mode == 'MAIN':
            price = await self.request('api', '/api/v3/ticker/price', 'GET', {
                'symbol': symbol
            }, send_signature=False)
            price = price['price']
        else:
            price = await self.request('fapi', '/fapi/v1/ticker/price', 'GET', {
                'symbol': symbol
            }, send_signature=False)
            price = price['price']
        price = float(price)
        return price

    async def get_all_latest_price(self, mode: str) -> Dict[str, float]:
        """
        获取市场所有货币对最新价格
        :param mode: 查询模式，MAIN或者FUTURE，代表现货或者期货
        """
        mode = mode.upper()

        # 判断mode是否填写正确
        if mode != 'MAIN' and mode != 'FUTURE':
            raise Exception('交易mode填写错误，只能为MAIN或者FUTURE')
        res = {}
        if mode == 'MAIN':
            price = await self.request('api', '/api/v3/ticker/price', 'GET', {}, send_signature=False)
            for e in price:
                res[e['symbol']] = float(e['price'])
        else:
            price = await self.request('fapi', '/fapi/v1/ticker/price', 'GET', {}, send_signature=False)
            for e in price:
                res[e['symbol']] = float(e['price'])
        return res

    async def set_bnb_burn(self, spot_bnb_burn: bool, interest_bnb_burn: bool):
        """
        设置BNB抵扣开关状态
        :param spot_bnb_burn: 是否使用bnb支付现货交易手续费
        :param interest_bnb_burn: 是否使用bnb支付杠杆贷款利息
        """
        data = {
            'spotBNBBurn': 'true' if spot_bnb_burn else 'false',
            'interestBNBBurn': 'true' if interest_bnb_burn else 'false',
            'timestamp': get_timestamp()
        }
        await self.request('api', '/sapi/v1/bnbBurn', 'POST', data)

    async def get_bnb_burn(self):
        """
        获取BNB抵扣开关状态
        """
        return await self.request('api', '/sapi/v1/bnbBurn', 'GET', {
            'timestamp': get_timestamp()
        })

    @staticmethod
    async def connect_websocket(mode: str, stream_name: str) -> websockets.WebSocketClientProtocol:
        """
        连接一个websocket\n
        :param mode: 只能为MAIN、FUTURE
        :param stream_name: 要订阅的数据流名字
        """
        if mode != 'MAIN' and mode != 'FUTURE':
            raise Exception('mode只能为MAIN、FUTURE')

        if mode == 'MAIN':
            ws = await websockets.connect('wss://stream.{}:9443/ws/{}'.format(base_url, stream_name))
        else:
            ws = await websockets.connect('wss://fstream.{}/ws/{}'.format(base_url, stream_name))

        return ws


async def create_client():
    return Client()
