# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import print_function

import numpy as np
from hashlib import sha1
from functools import wraps
from six.moves import cPickle
import weakref
from warnings import warn
import time, sys
import os, os.path, stat, string
from six import iteritems

from . import config

def _format_filename(s):
    """
    Take a string and return a valid filename constructed from the string.
    Uses a whitelist approach: any characters not present in valid_chars are
    removed. Also spaces are replaced with underscores.
    """
    valid_chars = frozenset("-_.() %s%s" % (string.ascii_letters, string.digits))
    return ''.join(c for c in s if c in valid_chars).replace(' ','_')


def cachable(func=None, version=None, cache_dir=config['cache_dir'],
             keepweakref=False, ignore=set(), verbose=True):
    """
    Decorator to mark long running functions, which should be saved to
    disk for a pickled version of their arguments.

    Arguments:
    func        - Shouldn't be supplied, but instead contains the
                  function, if the decorator is used without arguments
    version     - if given it is saved together with the arguments and
                  must be the same as the cache to be valid.
    cache_dir   - where to save the cached files, if it does not exist
                  it is created (default defined by ~/.vresutils.config)
    keepweakref - Also store a weak reference and return it instead of
                  rereading from disk (default: False).
    ignore      - Set of kwd arguments not to take into account.
    verbose     - Output cache hits and timing information (default:
                  True).
    """

    if not os.path.isdir(cache_dir):
        os.mkdir(cache_dir)
        gid = None
        mode = None
    else:
        st = os.stat(cache_dir)
        gid = st.st_gid
        # mode is bitmask of the same rights as the directory without
        # exec rights for anybody
        mode = stat.S_IMODE(st.st_mode) & ~(stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    def deco(func):
        """
        Wrap function to check for a cached result. Everything is
        pickled to a file of the name
        cache_dir/<funcname>_param1_param2_kw1key.kw1val
        (it would be better to use np.save/np.load for numpy arrays)
        """

        cache_fn = cache_dir + "/" + func.__module__ + "." + func.__name__ + "_"
        if version is not None:
            cache_fn += _format_filename("ver" + str(version) + "_")

        if keepweakref:
            cache = weakref.WeakValueDictionary()

        def name(x):
            y = str(x)
            if len(y) > 40:
                y = sha1(y).hexdigest()
            return y

        @wraps(func)
        def wrapper(*args, **kwds):
            recompute = kwds.pop('recompute', False)

            # Check if there is a cached version
            fn = cache_fn + _format_filename(
                '_'.join(name(a) for a in args) + '_' +
                '_'.join(name(k) + '.' + name(v)
                         for k,v in iteritems(kwds)
                         if k not in ignore) +
                '.pickle'
            )

            ret = None
            if not recompute and keepweakref and fn in cache:
                return cache[fn]
            elif not recompute and os.path.exists(fn):
                try:
                    with open(fn, 'rb') as f:
                        with optional(
                                verbose,
                                timer("Serving call to {} from file {}"
                                      .format(func.__name__, os.path.basename(fn)))
                        ):
                            ret = cPickle.load(f)
                except Exception as e:
                    warn("Couldn't unpickle from %s: %s" % (fn, e.args[0]))

            if ret is None:
                with optional(
                        verbose,
                        timer("Caching call to {} in {}"
                              .format(func.__name__, os.path.basename(fn)))
                ):
                    ret = func(*args, **kwds)
                    try:
                        with open(fn, 'wb') as f:
                            if gid: os.fchown(f.fileno(), -1, gid)
                            if mode: os.fchmod(f.fileno(), mode)
                            cPickle.dump(ret, f, protocol=-1)
                    except Exception as e:
                        warn("Couldn't pickle to %s: %s" % (fn, e.args[0]))

            if keepweakref and ret is not None:
                cache[fn] = ret

            return ret

        return wrapper

    if callable(func):
        return deco(func)
    else:
        return deco

class timer(object):
    level = 0
    opened = False

    def __init__(self, name=""):
        self.name = name

    def __enter__(self):
        if self.opened:
            sys.stdout.write("\n")

        if len(self.name) > 0:
            sys.stdout.write((".. " * self.level) + self.name + ": ")
        sys.stdout.flush()

        self.__class__.level += 1
        self.__class__.opened = True

        self.start = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.opened:
            sys.stdout.write(".. " * self.level)

        if exc_type is None:
            stop = time.time()
            usec = (stop - self.start) * 1e6
            if usec < 1000:
                print("%.1f usec" % usec)
            else:
                msec = usec / 1000
                if msec < 1000:
                    print("%.1f msec" % msec)
                else:
                    sec = msec / 1000
                    print("%.1f sec" % sec)
        else:
            print("failed")
        sys.stdout.flush()

        self.__class__.level -= 1
        self.__class__.opened = False
        return False

class optional(object):
    def __init__(self, variable, contextman):
        self.variable = variable
        self.contextman = contextman

    def __enter__(self):
        if self.variable:
            return self.contextman.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.variable:
            return self.contextman.__exit__(exc_type, exc_val, exc_tb)
        return False

def staticvars(**vars):
    def deco(fn):
        fn.__dict__.update(vars)
        return fn
    return deco

class CachedAttribute(object):
    '''
    Computes attribute value and caches it in the instance.
    From the Python Cookbook (Denis Otkidach)
    This decorator allows you to create a property which can be
    computed once and accessed many times. Sort of like memoization.
    '''
    def __init__(self, method, name=None, doc=None):
        # record the unbound-method and the name
        self.method = method
        self.name = name or method.__name__
        self.__doc__ = doc or method.__doc__
    def __get__(self, inst, cls):
        if inst is None:
            # instance attribute accessed on class, return self
            # You get here if you write `Foo.bar`
            return self
        # compute, cache and return the instance's attribute value
        result = self.method(inst)
        # setattr redefines the instance's attribute so this doesn't get called again
        setattr(inst, self.name, result)
        return result

def indexer(func):
    '''
    Decorator to turn a method into an object with a __getitem__ method.
    Can be used to turn a method into some extended getitem equivalent.
    '''
    class Indexer(object):
        def __init__(self, inst):
            self.inst = inst
        def __getitem__(self, key):
            return func(self.inst, key)
    return CachedAttribute(lambda self: Indexer(self), name=func.__name__, doc=func.__doc__)