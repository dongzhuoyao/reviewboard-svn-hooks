#!/usr/bin/python
# -*- coding:utf8 -*-
import os
import sys
import subprocess
import urllib2
import cookielib
import base64
import re
import shelve
import datetime
import ConfigParser
import traceback
try:
    import json
except ImportError:
    import simplejson as json

from urlparse import urljoin

from .utils import get_cmd_output, split

def get_os_conf_dir():
    platform = sys.platform
    if platform.startswith('win'):
        try:
            return os.environ['ALLUSERSPROFILE']
        except KeyError:
            print >>sys.stderr, 'Unspported operation system:%s'%platform
            sys.exit(1)
    return '/etc'

def get_os_temp_dir():
    import tempfile
    return tempfile.gettempdir()

def get_os_log_dir():
    platform = sys.platform
    if platform.startswith('win'):
        return get_os_conf_dir()
    return '/var/log'

OS_CONF_DIR = get_os_conf_dir()

conf = ConfigParser.ConfigParser()

conf_file = os.path.join(OS_CONF_DIR, 'reviewboard-svn-hooks', 'conf.ini')
if not conf.read(conf_file):
    raise StandardError('invalid configuration file:%s'%conf_file)


COOKIE_FILE = os.path.join(get_os_temp_dir(), 'reviewboard-svn-hooks-cookies.txt')

DEBUG = conf.getint('common', 'debug')

def debug(s):
    if not DEBUG:
        return
    f = open(os.path.join(get_os_log_dir(), 'reviewboard-svn-hooks', 'debug.log'), 'at')
    print >>f, str(datetime.datetime.now()), s
    f.close()

RB_SERVER = conf.get('reviewboard', 'url')
USERNAME = conf.get('reviewboard', 'username')
PASSWORD = conf.get('reviewboard', 'password')

MIN_SHIP_IT_COUNT = conf.getint('rule', 'min_ship_it_count')
MIN_EXPERT_SHIP_IT_COUNT = conf.getint('rule', 'min_expert_ship_it_count')
experts = conf.get('rule', 'experts')
EXPERTS = split(experts)
review_path = conf.get('rule', 'review_path')
REVIEW_PATH = split(review_path)
ignore_path = conf.get('rule', 'ignore_path')
IGNORE_PATH = split(ignore_path)

class SvnError(StandardError):
    pass

class Opener(object):
    def __init__(self, server, username, password, cookie_file = None):
        self._server = server
        if cookie_file is None:
            cookie_file = COOKIE_FILE
        self._auth = base64.b64encode(username + ':' + password)
        cookie_jar = cookielib.MozillaCookieJar(cookie_file)
        cookie_handler = urllib2.HTTPCookieProcessor(cookie_jar)
        self._opener = urllib2.build_opener(cookie_handler)

    def open(self, path, ext_headers, *a, **k):
        url = urljoin(self._server, path)
        return self.abs_open(url, ext_headers, *a, **k)

    def abs_open(self, url, ext_headers, *a, **k):
        debug('url open:%s' % url)
        r = urllib2.Request(url)
        for k, v in ext_headers:
            r.add_header(k, v)
        r.add_header('Authorization', 'Basic ' + self._auth)
        try:
            rsp = self._opener.open(r)
            return rsp.read()
        except urllib2.URLError, e:
            raise SvnError(str(e))

def make_svnlook_cmd(directive, repos, txn):
    def get_svnlook():
        platform = sys.platform
        if platform.startswith('win'):
            return get_cmd_output(['where svnlook']).split('\n')[0].strip()
        return 'svnlook'

    cmd =[get_svnlook(), directive, '-t',  txn, repos]
    debug(cmd)
    return cmd

def get_review_id(repos, txn):
    #get message id from commit message,namely log
    svnlook = make_svnlook_cmd('log', repos, txn)
    log = get_cmd_output(svnlook)
    debug(log)
    rid = re.search(r'review:([0-9]+)', log, re.M | re.I)
    if rid:
        return rid.group(1)
    raise SvnError('No review id.')
    # 'No review id' will be displayed in svn client

def add_to_rid_db(rid):
    USED_RID_DB = shelve.open(os.path.join(get_os_conf_dir(),
        'reviewboard-svn-hooks',
        'rb-svn-hooks-used-rid.db'))
    if USED_RID_DB.has_key(rid):
        raise SvnError, "review-id(%s) is already used."%rid
    USED_RID_DB[rid] = rid
    USED_RID_DB.sync()
    USED_RID_DB.close()

def check_rb(repos, txn):
    rid = get_review_id(repos, txn)
    path = 'api/review-requests/' + str(rid) + '/reviews/'
    opener = Opener(RB_SERVER, USERNAME, PASSWORD)
    rsp = opener.open(path, {})
    #load json data from response
    reviews = json.loads(rsp)
    if reviews['stat'] != 'ok':
        raise SvnError, "get reviews error."
    #ship_it_users record the "ship it" users number
    ship_it_users = set()
    for item in reviews['reviews']:
        ship_it = int(item['ship_it'])
        if ship_it:
            ship_it_users.add(item['links']['user']['title'])
    
    if len(ship_it_users) < MIN_SHIP_IT_COUNT:
        raise SvnError, "not enough of ship_it."
    expert_count = 0
    for user in ship_it_users:
        if user in EXPERTS:
            expert_count += 1
    if expert_count < MIN_EXPERT_SHIP_IT_COUNT:
        raise SvnError, 'not enough of key user ship_it.'
    #save reviewid in sql
    add_to_rid_db(rid)

def is_ignorable(changed):
    for line in changed.split('\n'):
        if not line.strip():
            continue
        f = line[4:]
        flg = False
        for ignore_path in IGNORE_PATH:
            if ignore_path in f:
                flg = True
                break
        if not flg:
            return False
    return True

def _main():
    debug('command:' + str(sys.argv))
    repos = sys.argv[1]
    txn = sys.argv[2]

    #get the changed file list
    svnlook = make_svnlook_cmd('changed', repos, txn)
    changed = get_cmd_output(svnlook)
    debug("changed files: "+changed)

    #ignore some file by "ignore_path"
    if is_ignorable(changed):
        return

    #if "review_path" is not set
    #when check_rb(),if no exception is raised,then directly return,thus the code is commited successfully
    if not REVIEW_PATH:
        check_rb(repos, txn)
        return 

    for line in changed.split('\n'):
        f = line[4:]
        for review_path in REVIEW_PATH:
            if review_path in f:
                check_rb(repos, txn)
                return

def main():
    try:
        _main()
    except SvnError, e:
        debug("svnerror. "+str(e))
        print >> sys.stderr, str(e)
        exit(1)
    except Exception, e:
        debug("Exception. "+str(e))
        print >> sys.stderr, str(e)
        import traceback
        traceback.print_exc(file=sys.stderr)
        exit(1)
    else:
        exit(0)

