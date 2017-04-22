# coding=utf-8
from xmlrpclib import SafeTransport

import certifi
import ssl
import os
from requests import Session
from retry.api import retry_call

pem_file = os.path.normpath(os.path.join(os.path.dirname(os.path.realpath(__file__)), "..", certifi.where()))


class RetryingSession(Session):
    proxied_functions = ("get", "post")

    def __init__(self):
        super(RetryingSession, self).__init__()
        self.verify = pem_file

    def retry_method(self, method, *args, **kwargs):
        return retry_call(getattr(super(RetryingSession, self), method), fargs=args, fkwargs=kwargs, tries=3, delay=1)

    def get(self, *args, **kwargs):
        return self.retry_method("get", *args, **kwargs)

    def post(self, *args, **kwargs):
        return self.retry_method("post", *args, **kwargs)

default_ssl_context = ssl.create_default_context(cafile=pem_file)


class TimeoutSafeTransport(SafeTransport):
    """Timeout support for ``xmlrpc.client.SafeTransport``."""
    def __init__(self, timeout, *args, **kwargs):
        SafeTransport.__init__(self, *args, **kwargs)
        self.timeout = timeout
        self.context = default_ssl_context

    def make_connection(self, host):
        print self.context
        c = SafeTransport.make_connection(self, host)
        c.timeout = self.timeout

        return c