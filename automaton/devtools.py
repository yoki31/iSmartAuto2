import asyncio
import json
import re
import urllib.parse as parser

import httpx
import websockets
from loguru import logger

from configs import configs


class Browser(object):
    @classmethod
    async def connect(cls):
        browser = cls(configs['browser']['port'])
        if configs['browser']['verify'] and not await browser._verify():
            return None
        return browser

    def __init__(self, dev_port):
        self.port = dev_port

    async def _verify(self):  # 校验客户端和配置文件中的用户是否相同
        logger.info('正在校验账号...')
        page = await self.wait_for_page(r'https?://.*')
        user_info = json.loads((await page.eval('''
            (function () {
                var xhr = new XMLHttpRequest()
                xhr.open('POST', 'https://school.ismartlearning.cn/client/user/student-info', false)
                xhr.withCredentials = true
                xhr.send(null)
                return xhr.responseText
            })()
        '''))['result']['value'])['data']
        spider_user = configs['user']['username']
        if spider_user != user_info['mobile'] and spider_user != user_info['username']:
            logger.warning('检测到 iSmart 客户端中登录的账号与配置文件中账号不符！')
            choice = input('继续使用可能会出现意料之外的问题，是否继续？[y/N]')
            if choice.lower() != 'y':
                return False
        else:
            logger.info('校验通过！')
        return True

    async def wait_for_page(self, regexp):  # 等待符合条件的页面出现
        async with httpx.AsyncClient() as client:
            while True:
                logger.info('等待可用页面...')
                try:
                    pages = (await client.get(f'http://127.0.0.1:{self.port}/json')).json()
                    for page in pages:
                        if re.fullmatch(regexp, page['url']) and 'webSocketDebuggerUrl' in page:
                            return Page(page['url'], page['webSocketDebuggerUrl'])
                except httpx.ConnectError:
                    pass
                await asyncio.sleep(2)

    # noinspection PyTypeChecker
    async def get_current(self):
        async with httpx.AsyncClient() as client:
            pages = (await client.get(f'http://127.0.0.1:{self.port}/json')).json()
            for page in pages:
                params = dict(parser.parse_qsl(parser.urlsplit(page['url']).query))
                if 'bookId' in params:
                    return params['courseId'], params['bookId']
                return params['courseId'], None


class Page(object):
    def __init__(self, url, dev_url):
        self.id = 0
        self.url, self.dev_url = url, dev_url

    async def send(self, command, params):
        async with websockets.connect(self.dev_url) as devtools:
            await devtools.send(json.dumps({
                'id': self.id,
                'method': command,
                'params': params
            }))
            self.id += 1
            return json.loads(await devtools.recv())

    async def eval(self, script):
        result = await self.send(
            'Runtime.evaluate', {
                'expression': script,
                'awaitPromise': True
            }
        )
        return result['result']

    async def submit(self, book_id, chapter_id, task_id, score, seconds, percent, user_id):  # 提交任务点的得分
        model = 'NetBrowser.submitTask("%s", "%s", "%s", 0, "%d", %d, %d, "%s");'
        result = f'%7B%22studentid%22:{user_id},%22testInfo%22:%7B%22answerdata%22:%22%22,%22markdatao%22:%22%22%7D%7D'
        return await self.eval(
            model % (book_id, chapter_id, task_id, score, seconds, percent, result)
        )
