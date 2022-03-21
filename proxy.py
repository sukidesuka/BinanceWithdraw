from email import header
from types import MethodDescriptorType
from flask import Flask, request

import json5 as json
import traceback
import requests

# 初始化flask框架
app = Flask(__name__)

# 用于客户端进行HTTP交互的端口
@app.route('/', methods=['POST'])
def root():
    try:
        method: str = request.form['method'].upper()
        url: str = request.form['url']
        api_key = json.loads(request.form['api_key'])

        headers = {
            'X-MBX-APIKEY': api_key
        }

        if method == 'POST':
            response = requests.post(url, headers=headers)
        elif method == 'GET':
            response = requests.get(url, headers=headers)
        else:
            raise('method必须为POST或者为GET')
        
        if response.status_code == 200:
            return json.dumps({
                'msg': 'success',
                'data': response.text
            })
        else:
            return json.dumps({
                'msg': 'error',
                'data': response.text
            })
    except:
        return json.dumps({
            'msg': 'error',
            'traceback': traceback.format_exc(),
        })


if __name__ == '__main__':
    # 读取配置文件
    with open('config.json', 'r', encoding='utf-8') as f:
        config = json.loads(f.read())

    print('检查配置文件是否有效...', end='')
    if 'port' in config and isinstance(config['port'], int) and \
        0 <= config['port'] <= 65535:
        print('OK')
    else:
        print('ERROR')
        raise('配置文件无效，请检查port输入是否正确')

    ip = '0.0.0.0'
    port = config['port']

    print('即将运行http服务器{}:{}'.format(ip, port))
    app.run(ip, port, debug=False, ssl_context='adhoc')
