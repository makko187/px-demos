# Copyright (c) 2020, 2021, Oracle and/or its affiliates.
#
# Licensed under the Universal Permissive License v 1.0 as shown at https://oss.oracle.com/licenses/upl/
#

import unittest
from mysqloperator.controller.utils import isotime
from mysqloperator.controller import config
from utils import tutil
from utils import kutil
import logging
import re
from utils.tutil import g_full_log
from utils.optesting import DEFAULT_MYSQL_ACCOUNTS, COMMON_OPERATOR_ERRORS

# TODO additional checks that could be done via webhooks
#  - version field (should be <= operator version)
#  -


class ClusterSpecAdmissionChecks(tutil.OperatorTest):
    """
    spec errors checked during admission (by CRD schema or webhook)
    """
    default_allowed_op_errors = COMMON_OPERATOR_ERRORS

    @classmethod
    def setUpClass(cls):
        cls.logger = logging.getLogger(__name__+":"+cls.__name__)
        super().setUpClass()

        g_full_log.watch_mysql_pod(cls.ns, "mycluster-0")
        g_full_log.watch_mysql_pod(cls.ns, "mycluster-1")

    @classmethod
    def tearDownClass(cls):
        g_full_log.stop_watch(cls.ns, "mycluster-1")
        g_full_log.stop_watch(cls.ns, "mycluster-0")

        super().tearDownClass()

    def tearDown(self):
        # none of the tests should create anything
        self.assertEqual([], kutil.ls_ic(self.ns))
        self.assertEqual([], kutil.ls_sts(self.ns))
        self.assertEqual([], kutil.ls_po(self.ns))

        return super().tearDown()

    def assertApplyFails(self, yaml, pattern):
        r = kutil.apply(self.ns, yaml, check=False)
        self.assertEqual(1, r.returncode)
        self.assertRegex(r.stdout.decode("utf8"), pattern)

    def test_0_invalid(self):
        """
        Checks:
        - Invalid field in spec
        """
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  secretName: mypwds
  bogus: 1234
"""
        self.assertApplyFails(
            yaml, r'ValidationError\(InnoDBCluster.spec\): unknown field "bogus" in com.oracle.mysql.v2alpha1.InnoDBCluster.spec')

    def test_1_name_too_long(self):
        """
        Checks:
        - cluster name can't be longer than allowed in innodb cluster (40 chars)
        """
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: veryveryveryveryveryveryveryverylongnamex
spec:
  secretName: mypwds
"""
        self.assertApplyFails(
            yaml, r'metadata.name in body should be at most 40 chars long')

    def test_1_no_name(self):
        """
        Checks:
        - metadata.name is mandatory
        (blocked even before the schema validation)
        """
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
spec:
  secretName: mypwds
"""
        self.assertApplyFails(yaml, r'resource name may not be empty')

    def test_1_no_secret(self):
        """
        Checks:
        - spec.secretName is mandatory
        """
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
"""
        self.assertApplyFails(
            yaml, r'ValidationError\(InnoDBCluster\): missing required field "spec" in com.oracle.mysql.v2alpha1.InnoDBCluster')

        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  instances: 1
"""
        self.assertApplyFails(
            yaml, r'error validating data: ValidationError\(InnoDBCluster.spec\): missing required field "secretName"')

    def test_1_instances(self):
        """
        Checks:
        - Invalid values for spec.instances (too small, too big, not number)
        """
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  secretName: mypwds
  instances: 0
"""
        self.assertApplyFails(
            yaml, 'spec.instances: Invalid value: 0: spec.instances in body should be greater than or equal to 1')

        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  secretName: mypwds
  instances: 14
"""
        self.assertApplyFails(
            yaml, 'spec.instances: Invalid value: 14: spec.instances in body should be less than or equal to 9')

        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  secretName: mypwds
  instances: "bla"
"""
        self.assertApplyFails(
            yaml, r'ValidationError\(InnoDBCluster.spec.instances\): invalid type for com.oracle.mysql.v2alpha1.InnoDBCluster.spec.instances: got "string", expected "integer"')

        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  secretName: mypwds
  mycnf: 42
"""
        self.assertApplyFails(
            yaml, r'spec.mycnf: Invalid value: "integer": spec.mycnf in body must be of type string: "integer"')

        # TODO bad imagePullPolicy


class ClusterSpecRuntimeChecksCreation(tutil.OperatorTest):
    """
    spec errors checked by the operator, once the ic object was accepted
    by the admission controllers.
    In all cases:
    - the status of the ic should become ERROR
    - an event describing the error should be posted

    Also:
    - fixing the error should recover from error
    - deleting cluster with error should be possible
    """
    default_allowed_op_errors = COMMON_OPERATOR_ERRORS

    @classmethod
    def setUpClass(cls):
        cls.logger = logging.getLogger(__name__+":"+cls.__name__)
        super().setUpClass()

        g_full_log.watch_mysql_pod(cls.ns, "mycluster-0")
        g_full_log.watch_mysql_pod(cls.ns, "mycluster-1")

    @classmethod
    def tearDownClass(cls):
        g_full_log.stop_watch(cls.ns, "mycluster-1")
        g_full_log.stop_watch(cls.ns, "mycluster-0")

        super().tearDownClass()

    def test_0_prepare(self):
        # this also checks that the root user can be completely customized
        kutil.create_user_secrets(
            self.ns, "mypwds", root_user="admin", root_host="%", root_pass="secret")

    def test_1_bad_secret_delete(self):
        """
        Checks:
        - secret that doesn't exist
        - cluster can be deleted after the failure
        """
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  instances: 1
  secretName: badsecret
"""
        start_time = isotime()

        kutil.apply(self.ns, yaml)

        self.wait_pod("mycluster-0", "Pending")

        # the initmysql container will fail during creation with
        # CreateContainerConfigError because the container is setup to read from
        # it to set MYSQL_ROOT_PASSWORD, so the operator or sidecars will never
        # run
        self.wait(kutil.ls_po, (self.ns,),
                  lambda pods: pods[0]["STATUS"] == "Init:CreateContainerConfigError")

        kutil.delete_ic(self.ns, "mycluster")

        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")
        kutil.delete_pvc(self.ns, None)

    def test_1_bad_secret_recover(self):
        pass

    def test_1_unsupported_version_delete(self):
        """
        Checks that setting an unsupported version is detected before any pods
        are created and that the cluster can be deleted in that state.
        """

        # create cluster with mostly default configs, but a specific server version
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  instances: 1
  secretName: mypwds
  version: "5.7.30"
"""
        kutil.apply(self.ns, yaml)

        self.wait(kutil.get_ic_ev, (self.ns, "mycluster"),
                  lambda evs: len(evs) > 0)

        # version is invalid/not supported, runtime check should prevent the
        # sts from being created
        self.assertFalse(kutil.ls_po(self.ns))
        self.assertFalse(kutil.ls_sts(self.ns))

        # there should be an event for the cluster resource indicating the
        # problem
        self.assertGotClusterEvent(
            "mycluster", type="Error", reason="InvalidArgument", msg="spec.version is 5.7.30 but must be between .*")

        # deleting the ic should work despite the error
        kutil.delete_ic(self.ns, "mycluster")

        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")
        kutil.delete_pvc(self.ns, None)

    def test_1_unsupported_version_recover(self):
        """
        Checks that setting an unsupported version is detected before any pods
        are created and that the cluster can be recovered by fixing the version.
        """

        # create cluster with mostly default configs, but a specific server version
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  instances: 1
  secretName: mypwds
  version: "5.7.30"
"""
        kutil.apply(self.ns, yaml)

        self.wait(kutil.get_ic_ev, (self.ns, "mycluster"),
                  lambda evs: len(evs) > 0)

        # fixing the version should let the cluster resume creation
        kutil.patch_ic(self.ns, "mycluster", {"spec": {
            "version": config.DEFAULT_VERSION_TAG
        }}, type="merge")

        # check cluster ok now
        self.wait_pod("mycluster-0", "Running")

        self.wait_ic("mycluster", "ONLINE")

        # cleanup
        kutil.delete_ic(self.ns, "mycluster")

        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")
        kutil.delete_pvc(self.ns, None)

    def test_2_bad_pod_delete(self):
        """
        Checks that using a bad spec that fails at the pod can be deleted.
        """
        # create cluster with mostly default configs, but a specific option
        # that will be accepted by the runtime checks but will fail at pod
        # creation
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  instances: 1
  secretName: mypwds
  imageRepository: invalid
"""
        kutil.apply(self.ns, yaml)

        self.wait_ic("mycluster", "PENDING")
        self.wait_pod("mycluster-0", ["Pending"])

        self.assertEqual(len(kutil.ls_po(self.ns)), 1)
        self.assertEqual(len(kutil.ls_sts(self.ns)), 1)

        def pod_error():
            return kutil.ls_po(self.ns)[0]["STATUS"] == "Init:ErrImageNeverPull"

        self.wait(pod_error)

        kutil.delete_ic(self.ns, "mycluster")
        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")
        kutil.delete_pvc(self.ns, None)

    def test_2_bad_pod_recover(self):
        """
        Checks that using a bad spec that fails at the pod can be recovered.
        """
        # create cluster with mostly default configs, but a specific option
        # that will be accepted by the runtime checks but will fail at pod
        # creation
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  instances: 1
  secretName: mypwds
  imageRepository: invalid
"""
        kutil.apply(self.ns, yaml)

        self.wait_ic("mycluster", "PENDING")
        self.wait_pod("mycluster-0", ["Pending"])

        self.assertEqual(len(kutil.ls_po(self.ns)), 1)
        self.assertEqual(len(kutil.ls_sts(self.ns)), 1)

        def pod_error():
            return kutil.ls_po(self.ns)[0]["STATUS"] == "Init:ErrImageNeverPull"

        self.wait(pod_error)

        # fixing the imageRepository should let the cluster resume creation
        kutil.patch_ic(self.ns, "mycluster", {"spec": {
            "imageRepository": config.DEFAULT_IMAGE_REPOSITORY
        }}, type="merge")

        # NOTE: seems we have to delete the pod to force it to be recreated
        # correctly
        kutil.delete_po(self.ns, "mycluster-0")

        # check cluster ok now
        self.wait_pod("mycluster-0", "Running")

        self.wait_ic("mycluster", "ONLINE")

        # cleanup
        kutil.delete_ic(self.ns, "mycluster")

        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")
        kutil.delete_pvc(self.ns, None)

    def test_9_destroy(self):
        kutil.delete_ic(self.ns, "mycluster")

        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")


class ClusterSpecRuntimeChecksModification(tutil.OperatorTest):
    """
    Same as ClusterSpecRuntimeChecksCreation, but for clusters that already
    exist and have invalid spec changes made.
    """
    default_allowed_op_errors = COMMON_OPERATOR_ERRORS

    @classmethod
    def setUpClass(cls):
        cls.logger = logging.getLogger(__name__+":"+cls.__name__)
        super().setUpClass()

        g_full_log.watch_mysql_pod(cls.ns, "mycluster-0")
        g_full_log.watch_mysql_pod(cls.ns, "mycluster-1")
        g_full_log.watch_mysql_pod(cls.ns, "mycluster-2")

    @classmethod
    def tearDownClass(cls):
        g_full_log.stop_watch(cls.ns, "mycluster-2")
        g_full_log.stop_watch(cls.ns, "mycluster-1")
        g_full_log.stop_watch(cls.ns, "mycluster-0")

        super().tearDownClass()

    def test_0_prepare(self):
        kutil.create_user_secrets(
            self.ns, "mypwds", root_user="root", root_host="%", root_pass="sakila")

        # create cluster with mostly default configs
        yaml = """
apiVersion: mysql.oracle.com/v2alpha1
kind: InnoDBCluster
metadata:
  name: mycluster
spec:
  instances: 3
  secretName: mypwds
"""

        kutil.apply(self.ns, yaml)

        self.wait_pod("mycluster-2", "Running")
        self.wait_ic("mycluster", "ONLINE", 3)

    def test_1_bad_upgrade(self):
        """
        Check invalid spec change that would cause a rolling restart by setting
        an invalid version.
        """
        kutil.patch_ic(self.ns, "mycluster", {"spec": {
            "version": "8.8.8"
        }}, type="merge")

        # Wait for mycluster-2 to fail upgrading
        def check(pods):
            print(pods[2]["STATUS"])
            return pods[2]["STATUS"] == "Init:ErrImageNeverPull"

        self.wait(kutil.ls_po, (self.ns,), check, delay=10, timeout=100)

        # check status of the cluster
        self.wait_ic("mycluster", ["ONLINE"], 2)

        # revert the version
        kutil.patch_ic(self.ns, "mycluster", {"spec": {
            "version": config.DEFAULT_SERVER_VERSION_TAG
        }}, type="merge")

        # delete the pod in error state so it can recover
        kutil.delete_po(self.ns, "mycluster-2")

        # Wait for mycluster-2 to recover
        self.wait_pod("mycluster-2", "Running")

        self.wait_ic("mycluster", ["ONLINE"], 3)

    def test_9_destroy(self):
        kutil.delete_ic(self.ns, "mycluster", 180)

        self.wait_pod_gone("mycluster-2")
        self.wait_pod_gone("mycluster-1")
        self.wait_pod_gone("mycluster-0")
        self.wait_ic_gone("mycluster")


# test only 1 or 2 bad syntax spec values and do the rest as unit-tests
# TODO find out what happens if version and image values conflict
# TODO invalid image repo, also auth error for repos
# errors after a cluster already exists should be recoverable
# before creation can be permanent
#   def test_replicas(self):
#   pass
#   def test_routers(self):
#   pass
#   def test_routers(self):
#   pass
