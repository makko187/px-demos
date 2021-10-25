# Copyright (c) 2020, 2021, Oracle and/or its affiliates.
#
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#


# Test utilities

import threading
from typing import List
import unittest
import subprocess
import logging
import os

from mysqloperator.controller.utils import isotime
from . import fmt
from . import kutil
import yaml
import time
import datetime
import sys
import traceback
import re
from .aggrlog import LogAggregator
from kubernetes.stream import stream
from kubernetes.client.api import core_v1_api
from kubernetes.stream.ws_client import ERROR_CHANNEL

g_test_data_dir = "."

debug_adminapi_sql = 0
testpod = os.getenv("TESTPOD_NAME") or "testpod"

g_full_log = LogAggregator()

logger = logging.getLogger("tutil")


def split_logs(logs):
    return logs.split("\n")


class Rule:
    def __init__(self):
        pass

    def forget(self):
        pass


class LogAnalyzer:
    def __init__(self, logs):
        self.logs = split_logs(logs)
        self.pos = None

    def allow(self, patterns):
        assert type(patterns) is list

    def forbid(self, patterns):
        assert type(patterns) is list

    def at_least(self, count, pattern):
        pass

    def at_most(self, count, pattern):
        pass

    def seek_first(self, pattern):
        pass

    def seek_last(self, pattern):
        pass

    def expect_after(self, message):
        pass

    def expect_before(self):
        pass

    def expect_between(self):
        pass


#

def strip_finalizers(ns, rsrc, name):
    r = kutil.get(ns, rsrc, name)

    if r and "finalizers" in r["metadata"]:
        logger.info(
            f"Stripping finalizers from {ns}/{name} ({r['metadata']['finalizers']})")
        kutil.patch(ns, rsrc, name, [
                    {"op": "remove", "path": "/metadata/finalizers"}], type="json")


def delete_ic(ns, name):
    logger.info(f"Delete ic {ns}/{name}")

    strip_finalizers(ns, "ic", name)
    kutil.delete_ic(ns, name, timeout=90)
    logger.info(f"ic {ns}/{name} deleted")


def wipe_ns(ns, extra_rsrc=[]):
    ics = kutil.ls_ic(ns)
    for ic in ics:
        delete_ic(ns, ic["NAME"])

    logger.info(f"Deleting remaining pods from {ns}")
    for pod in kutil.ls_po(ns):
        strip_finalizers(ns, "po", pod["NAME"])
    kutil.delete_po(ns, None, timeout=90)

    for rsrc in kutil.ALL_RSRC_TYPES + extra_rsrc:
        if rsrc != "po" and rsrc != "ic":
            logger.info(f"- Deleting {rsrc} from {ns}...")
            kutil.delete(ns, rsrc, None, timeout=90)

    try:
        kutil.delete_ns(ns)
    except subprocess.CalledProcessError as e:
        if "Upon completion, this namespace will automatically be purged by the system." in e.stderr.decode("utf8"):
            for i in range(60):
                if ns not in [n["NAME"] for n in kutil.ls_ns()]:
                    break
                time.sleep(1)


def wipe_pv():
    kutil.delete_pv(None)

#


class EventWatcher(threading.Thread):
    def __init__(self):
        pass

    def check(self):
        pass

    def add_pod_watch(self, ns, name, badlist):
        pass

    def add_ic_watch(self, ns, name, badlist):
        pass


class TestTracer:
    def __init__(self):
        self.source_cache = {}
        self.basedir = "/"
        self.trace_all = False
        self.enabled = False

    def getline(self, filename, lineno):
        if filename == "<string>":
            return None
        f = self.source_cache.get(filename)
        if not f:
            f = [l.rstrip() for l in open(filename).readlines()]
            self.source_cache[filename] = f
        return f[lineno-1]

    def localtrace(self, frame, why, arg, parent=None):
        code = frame.f_code
        filename = code.co_filename
        lineno = frame.f_lineno

        filename = filename.replace(self.basedir+"/", "")
        fn = os.path.basename(filename)

        if why == "line":
            line = self.getline(filename, lineno)
            if parent:
                g_full_log.annotate(f"{fn}:{lineno}: {parent}: {line}")
            print(fmt.cyan(f"{fn}:{lineno}: {line}"))
            return lambda f, w, a: self.localtrace(f, w, arg, parent)
        elif why == "call":
            if parent:
                print(fmt.cyan(f"{fn}:{lineno}: {code.co_name} >>"))
            return lambda f, w, a: self.localtrace(f, w, arg, None)
        elif why == "return":
            if parent:
                if "self" in frame.f_locals:
                    if isinstance(frame.f_locals["self"], OperatorTest):
                        print(fmt.purple(
                            f"{fn}:{lineno}: <<<< {frame.f_locals['self'].__class__.__name__}.{code.co_name}"))
                    else:
                        print(fmt.cyan(
                            f"{fn}:{lineno}: <<<< {frame.f_locals['self'].__class__.__name__}.{code.co_name}"))
                elif "cls" in frame.f_locals:
                    print(fmt.cyan(
                        f"{fn}:{lineno}: <<<< {frame.f_locals['cls'].__name__}.{code.co_name}"))
                else:
                    print(fmt.cyan(f"{fn}:{lineno}: <<<< {code.co_name}"))
            else:
                print(fmt.cyan(f"{fn}:{lineno}: << {code.co_name}"))
            return lambda f, w, a: self.localtrace(f, w, arg, None)
        elif why == "exception":
            if parent:
                g_full_log.annotate(f"exception at {fn}:{lineno}")
            print(fmt.red(f"{fn}:{lineno}: EXCEPTION"))
            return lambda f, w, a: self.localtrace(f, w, arg, parent)
        else:
            assert False, why

    def globaltrace(self, frame, why, arg):
        if why == "call":
            code = frame.f_code
            filename = frame.f_globals.get('__file__', None)
            lineno = frame.f_lineno

            if filename and (filename.startswith(self.basedir) or not filename.startswith("/")):
                filename = filename.replace(self.basedir+"/", "")
                fn = os.path.basename(filename)

                if "_t.py" in filename or self.trace_all:
                    print()
                    if "self" in frame.f_locals:
                        if isinstance(frame.f_locals["self"], OperatorTest):
                            g_full_log.annotate(
                                f"Begin Test {frame.f_locals['self'].__class__.__name__}.{code.co_name}")
                            print(fmt.purple(
                                f"{fn}:{lineno}: {frame.f_locals['self'].__class__.__name__}.{code.co_name} >>>>"))
                            return lambda f, w, a: self.localtrace(f, w, arg, code.co_name)
                        else:
                            print(fmt.cyan(
                                f"{fn}:{lineno}: {frame.f_locals['self'].__class__.__name__}.{code.co_name} >>>>"))
                    elif "cls" in frame.f_locals:
                        print(fmt.cyan(
                            f"{fn}:{lineno}: {frame.f_locals['cls'].__name__}.{code.co_name} >>>>"))
                    else:
                        print(fmt.cyan(f"{fn}:{lineno}: {code.co_name} >>>>"))
                    return lambda f, w, a: self.localtrace(f, w, arg)

            return None
        else:
            assert False, why

    def install(self):
        if self.enabled:
            print("Enabled tracer")
            sys.settrace(self.globaltrace)


tracer = TestTracer()


class OperatorTest(unittest.TestCase):
    logger = logging
    ns = "testns"
    op_stdout = []
    op_check_stdout = None
    default_allowed_op_errors: List[str]

    @classmethod
    def setUpClass(cls):
        cls.logger.info(f"Starting {cls.__name__}")

        leftovers = kutil.ls_all_raw(cls.ns)
        if leftovers:
            cls.logger.error("Namespace not empty before test: %s", leftovers)
            raise Exception(f"Namespace {cls.ns} not empty")

        kutil.create_ns(cls.ns)

        # stdout from operator
        cls.op_stdout = []
        # errors collected from operator output that indicate an unexpected
        # error happened, which would mean the operator broke
        cls.op_fatal_errors = []
        cls.op_logged_errors = []
        cls.op_log_errors = []
        cls.op_exception = []

        def check_operator_output(line):
            if "[CRITICAL]" in line or "[ERROR   ]" in line:
                cls.op_logged_errors.append(line)
            elif line.startswith("Traceback (most recent call last):"):
                cls.op_exception.append(line)
            elif cls.op_exception:
                if line.startswith("["):
                    stack = "".join(cls.op_exception)
                    # Ignore error caused by bug in kopf
                    if "ClientResponseError: 422" in stack:
                        pass
                    else:
                        cls.op_fatal_errors.append(stack)
                    cls.op_exception = []
                else:
                    cls.op_exception.append(line)

        # TODO monitor for operator pod restarts (from crashes)
        g_full_log.on_operator = check_operator_output

    @classmethod
    def tearDownClass(cls):
        kutil.delete_pvc(cls.ns, None)

        leftovers = kutil.ls_all_raw(cls.ns)
        if leftovers:
            cls.logger.error(
                "Namespace not empty at the end of the test case!")
            cls.logger.info("%s", leftovers)
            wipe_ns(cls.ns)

    def setUp(self):
        self.allowed_op_logged_errors = self.default_allowed_op_errors[:]
        self.start_time = isotime()

    def tearDown(self):
        self.check_operator_exceptions()

        # reset operator error counter
        self.op_fatal_errors = []
        self.op_logged_errors = []

    def assertGotClusterEvent(self, cluster, after=None, *, type, reason, msg):
        if after is None:
            after = self.start_time

        if isinstance(msg, str):
            msgpat = re.compile(f"^{msg}$")
        else:
            msgpat = re.compile(msg)

        events = kutil.get_ic_ev(
            self.ns, cluster, after=after, fields=["message", "reason", "type"])

        events = [(ev['type'], ev['reason'], ev['message']) for ev in events]

        for t, r, m in events:
            if t == type and r == reason and msgpat.match(m):
                break
        else:
            print(f"Events for {cluster}", "\n".join([str(x) for x in events]))

            self.fail(
                f"Event ({type}, {reason}, {msg}) not found for {cluster}")

    def check_operator_exceptions(self):
        # Raise an exception if there's no hope that the operator will make progress
        # (e.g. because of an unhandled exception)
        if len(self.op_fatal_errors) > 0:
            self.logger.critical(
                fmt.red("Operator exception: ") + "\n    ".join(self.op_fatal_errors))
        self.assertEqual(len(self.op_fatal_errors), 0,
                         "Unexpected operator exceptions detected")

        # Check for logged errors from the operator
        op_errors = []
        for err in self.op_logged_errors:
            for allowed in self.allowed_op_logged_errors:
                if re.search(allowed, err):
                    break
            else:
                op_errors.append(err.rstrip())
        if op_errors:
            self.logger.critical(
                fmt.red("Unexpected operator errors: ") + "\n    " + "\n    ".join(op_errors))
        self.assertEqual(len(op_errors), 0,
                         "Unexpected operator exceptions detected")

    def check_pod_errors(self):
        # Raise an exception if pods enter an error state they're not expected to
        pass  # TODO

    def wait(self, fn, args=tuple(), check=None,  timeout=60, delay=2):
        # TODO abort watchers when nothing new gets printed by operator for a while too
        self.check_operator_exceptions()

        timeout //= delay

        r = None
        for i in range(timeout):
            r = fn(*args)
            if check:
                ret = check(r)
                if ret:
                    return ret
            else:
                if r:
                    return r
            time.sleep(delay)
            self.check_operator_exceptions()
            self.check_pod_errors()

        if check:
            self.logger.error(
                f"Waited condition never became true. Last value was {r}")
        else:
            self.logger.error("Waited condition never became true")

        raise Exception("Timeout waiting for condition")

    def wait_ic(self, name, status_list, num_online=None, ns=None, timeout=200):
        """
        Wait for given ic object to reach one of the states in the list.
        Aborts on timeout or when an unexpected error is detected in the operator.
        """
        self.assertNotEqual(kutil.wait_ic(ns or self.ns, name, status_list, num_online=num_online,
                                          checkabort=self.check_operator_exceptions, timeout=timeout), None, "timeout waiting for cluster")

    def wait_pod(self, name, status_list, ns=None):
        """
        Wait for given pod object to reach one of the states in the list.
        Aborts on timeout or when an unexpected error is detected in the operator.
        """
        self.assertNotEqual(kutil.wait_pod(ns or self.ns, name, status_list,
                                           checkabort=self.check_operator_exceptions), None, "timeout waiting for pod")

    def wait_ic_gone(self, name, ns=None):
        kutil.wait_ic_gone(ns or self.ns, name,
                           checkabort=self.check_operator_exceptions)

    def wait_pod_gone(self, name, ns=None):
        kutil.wait_pod_gone(ns or self.ns, name,
                            checkabort=self.check_operator_exceptions)
