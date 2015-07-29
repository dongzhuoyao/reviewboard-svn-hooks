#!/usr/bin/python
# -*- coding:utf8 -*-
import os
import sys
import subprocess
import urllib2
import cookielib
import base64
import re
from urlparse import urljoin
import shlex
import shelve

import ConfigParser
try:
    import json
except ImportError:
    import simplejson as json

def get_cmd_output_old(cmd):
    p = subprocess.Popen(cmd,
            stdin = None,
            stdout = subprocess.PIPE,
            stderr = subprocess.PIPE)
    return p.communicate()[0]

def get_cmd_output(cmd):
    return os.popen(' '.join(cmd)).read()

def split(s):
#    return set([i.strip() for i in shlex.split(s, posix = False) if i.strip()])
    return set([i.strip() for i in s.split(',') if i.strip()])

