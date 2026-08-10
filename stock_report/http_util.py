#!/usr/bin/env python3
"""带重试与指数退避的 HTTP 取数。

原来各抓取脚本都是裸 `requests.get(...)` 包一层 try/except，任何失败（包括
新浪偶发的 502、腾讯限流的 429）都直接判死并把整批数据丢掉。实测这是"技术
指标经常整片缺失"的主要来源之一：不是源不可用，是一次抖动就放弃了。

策略（与 a-share-skill 的实时行情脚本一致）：
  - 429 / 500 / 502 / 503 / 504 以及网络异常  -> 重试，指数退避 + 随机抖动
  - 403                                        -> **不重试**，直接判定该 provider
                                                  不可用，由调用方切源。反复请求
                                                  只会让封禁更久。
  - 其余 4xx                                   -> 不重试（请求本身有问题）
"""
import random
import time

import requests

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
# 403 单列：不是"暂时失败"，是"这个源不给你用"，应当立即切换 provider
SWITCH_PROVIDER_STATUS = frozenset({403})

DEFAULT_ATTEMPTS = 3
DEFAULT_BACKOFF = (0.5, 1.0, 2.0)


class ProviderBlocked(Exception):
    """provider 明确拒绝（403）。调用方应切换数据源而不是重试。"""


def _sleep_for(attempt, backoff, jitter, sleeper):
    base = backoff[min(attempt, len(backoff) - 1)]
    sleeper(base + random.uniform(0, jitter))


def request_with_retry(url, *, headers=None, timeout=10, attempts=DEFAULT_ATTEMPTS,
                       backoff=DEFAULT_BACKOFF, jitter=0.25, session=None,
                       sleeper=time.sleep, encoding=None):
    """返回 requests.Response；重试耗尽抛最后一次异常，403 抛 ProviderBlocked。"""
    getter = (session or requests).get
    last_error = None
    for attempt in range(attempts):
        try:
            response = getter(url, headers=headers, timeout=timeout)
        except Exception as exc:                      # 网络层异常：可重试
            last_error = exc
            if attempt == attempts - 1:
                break
            _sleep_for(attempt, backoff, jitter, sleeper)
            continue

        if response.status_code in SWITCH_PROVIDER_STATUS:
            raise ProviderBlocked(f'{url} -> HTTP {response.status_code}')
        if response.status_code in RETRY_STATUS:
            last_error = requests.HTTPError(f'{url} -> HTTP {response.status_code}')
            if attempt == attempts - 1:
                break
            _sleep_for(attempt, backoff, jitter, sleeper)
            continue

        if encoding:
            response.encoding = encoding
        return response

    raise last_error if last_error else RuntimeError(f'{url} failed with no error recorded')


def get_text(url, *, default='', **kwargs):
    """取文本，任何失败返回 default 并打印原因——供"缺了也要继续"的调用点使用。"""
    try:
        return request_with_retry(url, **kwargs).text
    except ProviderBlocked as exc:
        print(f'[http] provider blocked, switch source: {exc}')
    except Exception as exc:
        print(f'[http] give up after retries: {url} ({type(exc).__name__}: {exc})')
    return default
